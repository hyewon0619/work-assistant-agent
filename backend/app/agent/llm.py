"""OpenAI 호환 /chat/completions 스트리밍 클라이언트.

LLM SDK 나 LangChain 없이 httpx 로 직접 부른다. 루프를 직접 짜야 진행 단계를 화면에 흘릴 수 있고,
한 턴에 온 여러 도구 호출을 병렬로 돌릴 수 있었다.
"""
import json
from dataclasses import dataclass, field
from typing import AsyncIterator, Protocol

import httpx

from app.config import settings


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str = ""


@dataclass
class Chunk:
    """스트림 조각. 본문 조각이거나, 스트림 끝에 모인 도구 호출 목록이다."""
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    done: bool = False


class LLMClient(Protocol):
    def stream(self, messages: list[dict], tools: list[dict] | None,
               tool_choice: str | None) -> AsyncIterator[Chunk]: ...


class LLMError(Exception):
    pass


class OpenAICompatibleClient:
    def __init__(self):
        self.timeout = httpx.Timeout(settings.read_timeout, connect=settings.connect_timeout)

    def _payload(self, messages, tools, tool_choice, stream=True, max_tokens=None) -> dict:
        body: dict = {
            "model": settings.llm_model,
            "messages": messages,
            "temperature": settings.llm_temperature,
            "stream": stream,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = tool_choice or "auto"
        if max_tokens:
            body["max_tokens"] = max_tokens
        if settings.llm_disable_thinking:
            body["chat_template_kwargs"] = {"enable_thinking": False}
        return body

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {settings.llm_api_key}"} if settings.llm_api_key else {}

    async def stream(self, messages, tools=None, tool_choice=None):
        url = f"{settings.llm_base_url.rstrip('/')}/chat/completions"
        calls: dict[int, ToolCall] = {}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream("POST", url, json=self._payload(messages, tools, tool_choice),
                                         headers=self._headers()) as resp:
                    if resp.status_code >= 400:
                        raise LLMError(f"LLM 서버 응답 오류({resp.status_code})")
                    async for line in resp.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        delta = json.loads(data)["choices"][0].get("delta", {})
                        if delta.get("content"):
                            yield Chunk(text=delta["content"])
                        for tc in delta.get("tool_calls") or []:
                            slot = calls.setdefault(tc.get("index", 0), ToolCall(id="", name=""))
                            slot.id = tc.get("id") or slot.id
                            fn = tc.get("function") or {}
                            slot.name = fn.get("name") or slot.name
                            slot.arguments += fn.get("arguments") or ""
        except httpx.ConnectTimeout as e:
            raise LLMError("LLM 서버에 연결하지 못했습니다.") from e
        except httpx.ReadTimeout as e:
            raise LLMError("LLM 응답이 너무 오래 걸립니다.") from e
        except httpx.HTTPError as e:
            raise LLMError("LLM 서버와 통신 중 오류가 발생했습니다.") from e
        yield Chunk(tool_calls=[c for _, c in sorted(calls.items())], done=True)

    async def warmup(self, system_prompt: str) -> None:
        """서버 기동 시 시스템 프롬프트 접두사를 캐시에 올려 둔다.

        측정해 보니 1,465토큰 접두사를 처음 처리하는 데 약 12초, 같은 접두사 두 번째는 약 0.5초였다.
        """
        url = f"{settings.llm_base_url.rstrip('/')}/chat/completions"
        body = self._payload([{"role": "system", "content": system_prompt},
                              {"role": "user", "content": "ping"}], None, None, stream=False, max_tokens=1)
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            await client.post(url, json=body, headers=self._headers())
