import json

from app.agent import guard
from app.agent.context import estimate_tokens, shrink
from app.agent.registry import BY_NAME, run_tool
from app.constants import SCHEDULE_KINDS


def test_small_model_arguments_are_coerced(conn):
    # 숫자를 문자열로 주거나 범위를 벗어나도 실행부에서 바로잡는다.
    res = run_tool(conn, "E001", "list_my_schedules", json.dumps({"days_ahead": "9999"}))
    assert res["days_ahead"] == 365


def test_enum_outside_whitelist_is_rejected(conn):
    res = run_tool(conn, "E001", "list_my_schedules", {"kind": "회식"})
    assert "error" in res and "기일" in res["error"]


def test_missing_required_value_asks_user_first(conn):
    res = run_tool(conn, "E001", "propose_schedule", {"case_id": "K00001", "kind": "기일"})
    assert "물어보세요" in res["error"]


def test_unknown_tool_and_broken_json_come_back_as_results(conn):
    assert "error" in run_tool(conn, "E001", "delete_everything", {})
    assert "error" in run_tool(conn, "E001", "find_cases", "{query:")


def test_schedule_kind_enum_is_the_shared_constant():
    # 화면과 에이전트가 같은 목록을 쓴다. 따로 적으면 종류가 늘 때 둘이 갈라진다.
    assert BY_NAME["propose_schedule"].params["kind"].enum is SCHEDULE_KINDS
    assert BY_NAME["list_my_schedules"].params["kind"].enum is SCHEDULE_KINDS


def test_grounding_guard():
    assert guard.needs_grounding_retry("계약 금액은 2,500만원입니다.", tool_calls_made=0)
    assert not guard.needs_grounding_retry("계약 금액은 2,500만원입니다.", tool_calls_made=1)
    assert not guard.needs_grounding_retry("어느 사건인지 골라 주세요.", tool_calls_made=0)


def test_control_token_cut_keeps_text_before_only():
    text = "다음 기일은 10월 12일입니다.<end_of_turn>다음 기일은 10월 12일입니다."
    assert guard.cut_control_tokens(text) == "다음 기일은 10월 12일입니다."


def test_model_written_links_are_removed():
    assert guard.strip_links("[사건 보기](/cases/K00001) 확인하세요 https://x.y/z") == "사건 보기 확인하세요 "


def test_shrink_marks_omitted_items_instead_of_dropping():
    big = {"count": 300, "cases": [{"title": "가" * 50, "memo": "나" * 1000} for _ in range(300)]}
    out = json.loads(shrink(big, 2000))
    assert estimate_tokens(json.dumps(out, ensure_ascii=False)) <= 2000
    assert out["cases_omitted"] + len(out["cases"]) == 300
    assert "없는" in out["_note"]
