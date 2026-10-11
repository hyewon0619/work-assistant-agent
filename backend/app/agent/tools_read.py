"""읽기 도구. 모든 조회는 visibility 의 절을 건다.

도구는 예외를 올리지 않고 결과(dict)를 돌려준다. 실패도 "오류" 결과로 모델에 보여 줘야
모델이 무엇이 잘못됐는지 알고 다른 길을 찾는다. 예외로 올리면 같은 도구를 그대로 다시 부른다.
"""
from app import case_summary, clock
from app.agent.search import keywords
from app.agent.visibility import NOT_FOUND, assigned_clause, case_is_visible, scope, visible_clause
from app.db import rows

CASE_COLUMNS = (
    "c.case_id, c.court_no, c.title, c.category, c.status, c.opened_at, c.closed_at, "
    "c.result, c.contract_amount, cl.name AS client_name, cl.kind AS client_kind"
)


def find_cases(conn, emp_id, query: str, status: str | None = None, limit: int = 10):
    terms = keywords(query)
    if not terms:
        return {"count": 0, "cases": [], "note": "검색어를 찾지 못했습니다. 의뢰인 이름이나 사건명을 물어보세요."}
    vis, vparams = visible_clause("c")
    likes, params = [], {}
    for i, t in enumerate(terms):
        params[f"t{i}"] = f"%{t}%"
        likes.append(
            f"(cl.name LIKE :t{i} OR c.title LIKE :t{i} OR c.court_no LIKE :t{i} OR c.category LIKE :t{i})"
        )
    where = [vis, "(" + " OR ".join(likes) + ")"]
    if status:
        where.append("c.status = :status")
        params["status"] = status
    sql = (
        f"SELECT {CASE_COLUMNS} FROM legal_case c JOIN client cl ON cl.client_id = c.client_id "
        f"WHERE {' AND '.join(where)} ORDER BY c.opened_at DESC LIMIT :limit"
    )
    found = rows(conn.execute(sql, scope(emp_id, vparams, params, limit=limit)))
    return {"count": len(found), "cases": found, "searched": terms}


def find_authorities(conn, emp_id, query: str, limit: int = 10):
    # 처분권자 명부는 사건과 무관한 공용 목록이다. 사건에 연결할 때 가시성 검사를 한다.
    terms = keywords(query) or [query.strip()]
    likes, params = [], {}
    for i, t in enumerate(terms):
        params[f"t{i}"] = f"%{t}%"
        likes.append(f"(a.name LIKE :t{i} OR a.org LIKE :t{i})")
    sql = f"SELECT a.auth_id, a.name, a.org, a.title FROM authority a WHERE {' OR '.join(likes)} LIMIT :limit"
    found = rows(conn.execute(sql, {**params, "limit": limit}))
    return {"count": len(found), "authorities": found}


def _guard(conn, emp_id, case_id):
    return None if case_is_visible(conn, emp_id, case_id) else {"error": NOT_FOUND}


def get_case_overview(conn, emp_id, case_id: str):
    if (err := _guard(conn, emp_id, case_id)):
        return err
    sql = (
        f"SELECT {CASE_COLUMNS} FROM legal_case c JOIN client cl ON cl.client_id = c.client_id "
        "WHERE c.case_id = :case_id"
    )
    return {"case": dict(conn.execute(sql, {"case_id": case_id}).fetchone())}


def get_case_authorities(conn, emp_id, case_id: str):
    if (err := _guard(conn, emp_id, case_id)):
        return err
    found = rows(conn.execute(
        "SELECT a.auth_id, a.name, a.org, a.title FROM case_authority ca "
        "JOIN authority a ON a.auth_id = ca.auth_id WHERE ca.case_id = :case_id",
        {"case_id": case_id},
    ))
    return {"case_id": case_id, "registered": bool(found), "authorities": found}


def get_case_meetings(conn, emp_id, case_id: str, limit: int = 5):
    if (err := _guard(conn, emp_id, case_id)):
        return err
    found = rows(conn.execute(
        "SELECT m.meeting_id, m.at, e.name AS author, m.content, m.lawyer_comment FROM meeting m "
        "JOIN employee e ON e.emp_id = m.author_emp_id WHERE m.case_id = :case_id "
        "ORDER BY m.at DESC LIMIT :limit",
        {"case_id": case_id, "limit": limit},
    ))
    return {"case_id": case_id, "count": len(found), "meetings": found}


def get_case_schedules(conn, emp_id, case_id: str, include_past: bool = False):
    if (err := _guard(conn, emp_id, case_id)):
        return err
    sql = "SELECT sched_id, kind, at, place, memo FROM schedule WHERE case_id = :case_id"
    if not include_past:
        sql += " AND at >= :today"
    found = rows(conn.execute(sql + " ORDER BY at", {"case_id": case_id, "today": clock.today().isoformat()}))
    return {"case_id": case_id, "count": len(found), "schedules": found}


def get_case_employees(conn, emp_id, case_id: str):
    if (err := _guard(conn, emp_id, case_id)):
        return err
    found = rows(conn.execute(
        "SELECT e.name, e.title, e.branch, cm.role FROM case_member cm "
        "JOIN employee e ON e.emp_id = cm.emp_id WHERE cm.case_id = :case_id ORDER BY cm.role",
        {"case_id": case_id},
    ))
    return {"case_id": case_id, "members": found}


def get_case_summary(conn, emp_id, case_id: str):
    # 사건 내용 요약은 기존 사건 단위 요약 서비스를 도구로 불러 재사용한다.
    if (err := _guard(conn, emp_id, case_id)):
        return err
    return {"case_id": case_id, "summary": case_summary.summarize(conn, case_id)}


def list_my_cases(conn, emp_id, status: str | None = "진행", category: str | None = None, limit: int = 20):
    clause, cparams = assigned_clause("c")
    where, params = [clause], {}
    if status:
        where.append("c.status = :status")
        params["status"] = status
    if category:
        where.append("c.category = :category")
        params["category"] = category
    base = f"FROM legal_case c JOIN client cl ON cl.client_id = c.client_id WHERE {' AND '.join(where)}"
    args = scope(emp_id, cparams, params)
    total = conn.execute(f"SELECT COUNT(*) {base}", args).fetchone()[0]
    found = rows(conn.execute(f"SELECT {CASE_COLUMNS} {base} ORDER BY c.opened_at DESC LIMIT :limit", {**args, "limit": limit}))
    return {"total": total, "shown": len(found), "cases": found}


def list_my_schedules(conn, emp_id, days_ahead: int = 7, kind: str | None = None):
    clause, cparams = assigned_clause("c")
    params = {"start": clock.today().isoformat(), "end": clock.days_from_today(days_ahead) + "T23:59"}
    sql = (
        "SELECT s.sched_id, s.case_id, c.title, cl.name AS client_name, s.kind, s.at, s.place "
        "FROM schedule s JOIN legal_case c ON c.case_id = s.case_id "
        "JOIN client cl ON cl.client_id = c.client_id "
        f"WHERE {clause} AND s.at BETWEEN :start AND :end"
    )
    if kind:
        sql += " AND s.kind = :kind"
        params["kind"] = kind
    found = rows(conn.execute(sql + " ORDER BY s.at", scope(emp_id, cparams, params)))
    return {"days_ahead": days_ahead, "count": len(found), "schedules": found}
