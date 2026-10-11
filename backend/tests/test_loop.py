import asyncio
import json

from app.agent.loop import run_agent
from app.config import settings
from conftest import open_conn


def run(llm, question="질문", history=None):
    async def go():
        return [ev async for ev in run_agent(question=question, user_message=question, emp_id="E001",
                                             history=history or [], llm=llm, open_conn=open_conn)]
    return asyncio.run(go())


def done(events):
    return next(e for e in events if e.get("stage") == "done")


def test_tool_then_answer_with_server_built_sources(fake_llm):
    llm = fake_llm([[("get_case_schedules", json.dumps({"case_id": "K00001"}))],
                    "다음 기일은 10월 12일 10시입니다."])
    final = done(run(llm))
    assert final["answer"] == "다음 기일은 10월 12일 10시입니다."
    assert final["sources"] == [{"case_id": "K00001", "title": "사기 고소", "url": "/cases/K00001"}]
    tool_msg = next(m for m in llm.requests[1]["messages"] if m["role"] == "tool")
    assert "S_DEMO1" in tool_msg["content"]


def test_fact_without_tool_call_forces_one_retry(fake_llm):
    llm = fake_llm(["계약 금액은 3,000만원입니다.",
                    [("get_case_overview", json.dumps({"case_id": "K00001"}))],
                    "계약 금액은 2,500만원입니다."])
    events = run(llm)
    assert llm.requests[1]["tool_choice"] == "required"
    assert any(e.get("type") == "reset" for e in events)
    assert done(events)["answer"] == "계약 금액은 2,500만원입니다."


def test_multiple_tool_calls_in_one_turn_all_run(fake_llm):
    llm = fake_llm([[("get_case_meetings", json.dumps({"case_id": "K00001"})),
                     ("get_case_authorities", json.dumps({"case_id": "K00002"}))],
                    "정리했습니다."])
    final = done(run(llm))
    assert final["tools_used"] == ["get_case_meetings", "get_case_authorities"]
    assert len([m for m in llm.requests[1]["messages"] if m["role"] == "tool"]) == 2


def test_last_round_has_no_tools(fake_llm):
    rounds = [[("list_my_cases", "{}")]] * (settings.max_tool_rounds - 1) + ["여기까지 확인했습니다."]
    llm = fake_llm(rounds)
    final = done(run(llm))
    assert llm.requests[-1]["tools"] is None
    assert final["answer"] == "여기까지 확인했습니다."


def test_ambiguous_name_becomes_choice_buttons(fake_llm):
    llm = fake_llm([[("find_cases", json.dumps({"query": "박민수"}))], "어느 사건인지 골라 주세요."])
    final = done(run(llm))
    assert final["choices"]["type"] == "case"
    assert {o["id"] for o in final["choices"]["options"]} == {"K00001", "K00002"}


def test_case_choice_suppresses_authority_choice(fake_llm):
    llm = fake_llm([[("find_cases", json.dumps({"query": "박민수"})),
                     ("find_authorities", json.dumps({"query": "서울중앙지방검찰청"}))],
                    "어느 사건인지 골라 주세요."])
    assert done(run(llm))["choices"]["type"] == "case"


def test_control_tokens_never_reach_the_screen(fake_llm):
    llm = fake_llm([[("list_my_cases", "{}")], "진행 중인 사건은 확인했습니다.<|im_end|>진행 중인 사건은 확인했습니다."])
    events = run(llm)
    streamed = "".join(e["text"] for e in events if e.get("type") == "token")
    assert "<|im_end|>" not in streamed
    assert done(events)["answer"] == "진행 중인 사건은 확인했습니다."


def test_tool_failure_is_shown_to_model_not_raised(fake_llm):
    llm = fake_llm([[("get_case_overview", "{}")], "어느 사건인지 알려 주세요."])
    run(llm)
    tool_msg = next(m for m in llm.requests[1]["messages"] if m["role"] == "tool")
    assert "물어보세요" in tool_msg["content"]


def test_history_is_capped(fake_llm):
    history = [{"question": f"q{i}", "answer": f"a{i}"} for i in range(20)]
    llm = fake_llm(["안녕하세요."])
    run(llm, history=history)
    users = [m for m in llm.requests[0]["messages"] if m["role"] == "user"]
    assert len(users) == settings.max_history_turns + 1
