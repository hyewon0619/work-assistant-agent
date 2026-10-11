from app.agent import tools_read
from app.agent.registry import TOOLS, run_tool
from app.agent.visibility import NOT_FOUND
from app.constants import ASSIGNED_ROLES


def _invisible_case(conn, emp_id):
    return conn.execute(
        "SELECT case_id FROM legal_case WHERE case_id NOT IN (SELECT case_id FROM case_member WHERE emp_id = ?) LIMIT 1",
        (emp_id,),
    ).fetchone()["case_id"]


def test_tool_schemas_have_no_emp_id():
    # 모델이 고른 값이 권한이 되면 안 된다.
    for tool in TOOLS:
        assert "emp_id" not in tool.schema()["function"]["parameters"]["properties"]


def test_known_id_outside_scope_is_blocked_on_every_case_tool(conn):
    other = _invisible_case(conn, "E001")
    for name in ("get_case_overview", "get_case_authorities", "get_case_meetings",
                 "get_case_schedules", "get_case_employees", "get_case_summary"):
        assert run_tool(conn, "E001", name, {"case_id": other}) == {"error": NOT_FOUND}


def test_forbidden_and_missing_cases_look_the_same(conn):
    other = _invisible_case(conn, "E001")
    forbidden = run_tool(conn, "E001", "get_case_overview", {"case_id": other})
    missing = run_tool(conn, "E001", "get_case_overview", {"case_id": "K99999"})
    assert forbidden == missing


def test_search_only_returns_visible_cases(conn):
    res = tools_read.find_cases(conn, "E001", "사기")
    visible = {r["case_id"] for r in conn.execute("SELECT case_id FROM case_member WHERE emp_id = 'E001'")}
    assert res["cases"] and all(c["case_id"] in visible for c in res["cases"])


def test_my_case_count_excludes_view_only(conn):
    marks = ",".join("?" for _ in ASSIGNED_ROLES)
    expected = conn.execute(
        f"SELECT COUNT(DISTINCT cm.case_id) FROM case_member cm JOIN legal_case c ON c.case_id = cm.case_id "
        f"WHERE cm.emp_id = 'E001' AND c.status = '진행' AND cm.role IN ({marks})",
        ASSIGNED_ROLES,
    ).fetchone()[0]
    assert tools_read.list_my_cases(conn, "E001")["total"] == expected


def test_view_only_member_can_read_but_it_is_not_counted(conn):
    row = conn.execute(
        "SELECT cm.case_id, cm.emp_id FROM case_member cm WHERE cm.role = '열람' AND NOT EXISTS "
        "(SELECT 1 FROM case_member x WHERE x.case_id = cm.case_id AND x.emp_id = cm.emp_id AND x.role != '열람') LIMIT 1"
    ).fetchone()
    assert "case" in tools_read.get_case_overview(conn, row["emp_id"], row["case_id"])
    mine = tools_read.list_my_cases(conn, row["emp_id"], status=None, limit=50)["cases"]
    assert row["case_id"] not in {c["case_id"] for c in mine}
