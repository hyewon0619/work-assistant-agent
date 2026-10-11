"""먼저 알려 주는 브리핑.

비서 창을 열면 질문을 기다리지 않고 지금 챙겨야 할 것을 먼저 보여 준다.
모델을 부르지 않는 결정적 규칙이라, 같은 날 같은 사람에게는 늘 같은 목록이 나온다.
각 항목에는 바로 이어서 물어볼 수 있는 후속 질문(action)이 붙는다.
"""
from app import clock
from app.agent.visibility import assigned_clause, scope
from app.constants import AUTHORITY_REQUIRED_CATEGORIES
from app.db import rows

UPCOMING_DAYS = 3
STALE_MEETING_DAYS = 30
HIGH_AMOUNT = 10_000_000
# 종류마다 몇 건만 보여 주고 나머지는 건수로 알린다. 매일 스무 줄이 뜨면 아무도 읽지 않는다.
PER_KIND = 3


def build_briefing(conn, emp_id: str) -> list[dict]:
    clause, cparams = assigned_clause("c")
    upcoming, no_authority, stale = [], [], []

    for s in rows(conn.execute(
        "SELECT s.case_id, s.kind, s.at, c.title, cl.name AS client_name FROM schedule s "
        "JOIN legal_case c ON c.case_id = s.case_id JOIN client cl ON cl.client_id = c.client_id "
        f"WHERE {clause} AND s.at BETWEEN :start AND :end ORDER BY s.at",
        scope(emp_id, cparams, start=clock.today().isoformat(),
              end=clock.days_from_today(UPCOMING_DAYS) + "T23:59"),
    )):
        upcoming.append({
            "level": "info", "case_id": s["case_id"],
            "text": f"{s['at'][5:10].replace('-', '/')} {s['at'][11:16]} {s['kind']} · {s['client_name']} {s['title']}",
            "action": f"{s['client_name']} 사건 {s['kind']} 준비할 거 정리해줘",
        })

    marks = ",".join(f":cat{i}" for i in range(len(AUTHORITY_REQUIRED_CATEGORIES)))
    cats = {f"cat{i}": v for i, v in enumerate(AUTHORITY_REQUIRED_CATEGORIES)}
    for c in rows(conn.execute(
        "SELECT c.case_id, c.title, cl.name AS client_name FROM legal_case c "
        "JOIN client cl ON cl.client_id = c.client_id "
        f"WHERE {clause} AND c.status = '진행' AND c.category IN ({marks}) "
        "AND NOT EXISTS (SELECT 1 FROM case_authority ca WHERE ca.case_id = c.case_id) "
        "ORDER BY c.opened_at",
        scope(emp_id, cparams, cats),
    )):
        no_authority.append({
            "level": "warn", "case_id": c["case_id"],
            "text": f"처분권자 미등록 · {c['client_name']} {c['title']}",
            "action": f"{c['client_name']} 사건 처분권자 등록하고 싶어",
        })

    for c in rows(conn.execute(
        "SELECT c.case_id, c.title, cl.name AS client_name, MAX(m.at) AS last_meeting "
        "FROM legal_case c JOIN client cl ON cl.client_id = c.client_id "
        "LEFT JOIN meeting m ON m.case_id = c.case_id "
        f"WHERE {clause} AND c.status = '진행' AND c.contract_amount >= :amount "
        "GROUP BY c.case_id HAVING last_meeting IS NULL OR last_meeting < :cutoff "
        "ORDER BY last_meeting",
        scope(emp_id, cparams, amount=HIGH_AMOUNT, cutoff=clock.days_from_today(-STALE_MEETING_DAYS)),
    )):
        since = c["last_meeting"][:10] if c["last_meeting"] else "기록 없음"
        stale.append({
            "level": "warn", "case_id": c["case_id"],
            "text": f"{STALE_MEETING_DAYS}일 이상 면담 없음(마지막 {since}) · {c['client_name']} {c['title']}",
            "action": f"{c['client_name']} 사건 면담 일정 잡아줘",
        })
    items: list[dict] = []
    for group, label in ((upcoming, "3일 내 일정"), (no_authority, "처분권자 미등록"), (stale, "장기 미면담")):
        items += group[:PER_KIND]
        if len(group) > PER_KIND:
            items.append({"level": group[0]["level"], "case_id": None, "action": None,
                          "text": f"{label} 외 {len(group) - PER_KIND}건 더 있음"})
    return items
