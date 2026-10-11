"""에이전트 루프. 프레임워크 없이 직접 구현했다.

직접 짠 이유
1. 진행 단계(plan → tool → answer → done)를 화면에 실시간으로 흘려야 했다.
2. "A 사건 면담이랑 B 사건 처분권자 알려줘" 같은 복합 질문에서 한 턴에 온 도구 호출을 병렬로 돌린다.

흐름: 모델 스트리밍 호출 → 본문 조각은 바로 전송, 도구 호출은 모아서 병렬 실행
→ 결과를 컨텍스트 창에 맞게 줄여 다시 넣기 → 최대 6회. 마지막 회차에는 도구를 주지 않는다.
도구만 부르다 답 없이 끝나는 것을 막기 위해서다.
"""
import asyncio
import json
from typing import AsyncIterator, Callable

from app.agent import guard
from app.agent.context import shrink
from app.agent.llm import LLMClient, LLMError
from app.agent.postprocess import build_extras
from app.agent.prompt import GROUNDING_RETRY, SYSTEM_PROMPT
from app.agent.registry import run_tool, tool_schemas
from app.config import settings

HOLD_BACK = 16  # 제어 토큰이 조각 경계에 걸쳐 올 수 있어 끝 몇 글자는 확정될 때까지 붙잡아 둔다.


class _Emitter:
    """누적 본문에서 제어 토큰 앞까지만, 아직 안 보낸 부분을 내보낸다."""

    def __init__(self):
        self.raw = ""
        self.sent = 0

    def feed(self, piece: str, final: bool = False) -> str:
        self.raw += piece
        clean = guard.cut_control_tokens(self.raw)
        limit = len(clean) if final or len(clean) < len(self.raw) else max(self.sent, len(clean) - HOLD_BACK)
        out = clean[self.sent:limit]
        self.sent = max(self.sent, limit)
        return out

    def text(self) -> str:
        return guard.cut_control_tokens(self.raw)


def history_messages(history: list[dict]) -> list[dict]:
    # 이력은 클라이언트가 들고 있다가 요청에 실어 올린다. 서버가 매 요청 이력을 다시 조회하지 않는다.
    out = []
    for turn in history[-settings.max_history_turns:]:
        out.append({"role": "user", "content": str(turn.get("question", ""))})
        out.append({"role": "assistant", "content": str(turn.get("answer", ""))})
    return out


async def _run_tools(open_conn: Callable, emp_id: str, calls) -> list[dict]:
    def one(call):
        with open_conn() as conn:
            return run_tool(conn, emp_id, call.name, call.arguments)
    return await asyncio.gather(*(asyncio.to_thread(one, c) for c in calls))


async def run_agent(
    *, question: str, user_message: str, emp_id: str, history: list[dict],
    llm: LLMClient, open_conn: Callable,
) -> AsyncIterator[dict]:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}, *history_messages(history),
                {"role": "user", "content": user_message}]
    schemas = tool_schemas()
    executed: list[dict] = []  # {"name", "args", "result"}
    tool_choice = "auto"
    retried = False
    answer = ""

    yield {"stage": "plan"}
    for round_no in range(settings.max_tool_rounds):
        last = round_no == settings.max_tool_rounds - 1
        emitter = _Emitter()
        calls = []
        try:
            async for chunk in llm.stream(messages, None if last else schemas, None if last else tool_choice):
                if chunk.text:
                    if (out := emitter.feed(chunk.text)):
                        yield {"type": "token", "text": out}
                if chunk.done:
                    calls = chunk.tool_calls
        except LLMError as e:
            yield {"stage": "error", "message": str(e)}
            return
        if (tail := emitter.feed("", final=True)):
            yield {"type": "token", "text": tail}

        if calls and not last:
            yield {"stage": "tool", "names": [c.name for c in calls]}
            messages.append({
                "role": "assistant", "content": emitter.text() or None,
                "tool_calls": [{"id": c.id or f"call_{round_no}_{i}", "type": "function",
                                "function": {"name": c.name, "arguments": c.arguments or "{}"}}
                               for i, c in enumerate(calls)],
            })
            results = await _run_tools(open_conn, emp_id, calls)
            budget = max(800, settings.context_budget_tokens // (2 * len(calls)))
            for i, (c, res) in enumerate(zip(calls, results)):
                executed.append({"name": c.name, "args": _safe_args(c.arguments), "result": res})
                messages.append({"role": "tool", "tool_call_id": c.id or f"call_{round_no}_{i}",
                                 "content": shrink(res, budget)})
            tool_choice = "auto"
            if emitter.text():
                yield {"type": "reset"}
            continue

        answer = guard.strip_links(emitter.text())
        if not retried and not last and guard.needs_grounding_retry(answer, len(executed)):
            retried = True
            tool_choice = "required"
            messages += [{"role": "assistant", "content": answer}, {"role": "user", "content": GROUNDING_RETRY}]
            yield {"type": "reset"}
            yield {"stage": "plan", "retry": True}
            continue
        break

    yield {"stage": "answer"}
    with open_conn() as conn:
        extras = build_extras(conn, emp_id, executed)
    yield {"stage": "done", "answer": answer, "tools_used": [e["name"] for e in executed], **extras}


def _safe_args(raw: str) -> dict:
    try:
        parsed = json.loads(raw or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}
