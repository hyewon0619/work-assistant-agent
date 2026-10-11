import os
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

# settings 는 import 시점에 만들어지므로 경로와 기준일을 먼저 고정한다.
_TMP = Path(tempfile.mkdtemp()) / "test.db"
os.environ["DB_PATH"] = str(_TMP)
os.environ["FIXED_TODAY"] = "2026-10-11"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from app import db  # noqa: E402
from app.agent.llm import Chunk, ToolCall  # noqa: E402
from scripts import generate_data  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    generate_data.main(_TMP)
    yield


@pytest.fixture
def conn():
    c = db.connect(_TMP)
    yield c
    c.close()


@contextmanager
def open_conn():
    c = db.connect(_TMP)
    try:
        yield c
    finally:
        c.close()


class FakeLLM:
    """회차별로 정해 둔 응답을 돌려주는 가짜 모델. 받은 요청도 기록한다."""

    def __init__(self, rounds):
        self.rounds = list(rounds)
        self.requests = []

    async def stream(self, messages, tools=None, tool_choice=None):
        self.requests.append({"messages": [dict(m) for m in messages], "tools": tools, "tool_choice": tool_choice})
        step = self.rounds.pop(0)
        if isinstance(step, str):
            for i in range(0, len(step), 5):
                yield Chunk(text=step[i:i + 5])
            yield Chunk(done=True)
        else:
            yield Chunk(tool_calls=[ToolCall(id=f"c{i}", name=n, arguments=a) for i, (n, a) in enumerate(step)], done=True)


@pytest.fixture
def fake_llm():
    return FakeLLM
