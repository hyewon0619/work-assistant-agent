import asyncio
import json
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from app import auth, clock, db, history
from app.agent import tools_read
from app.agent.llm import OpenAICompatibleClient
from app.agent.loop import run_agent
from app.agent.prompt import SYSTEM_PROMPT, build_user_message
from app.agent.visibility import NOT_FOUND
from app.briefing import build_briefing
from app.config import settings
from app.constants import ASSIGNED_ROLES, CASE_CATEGORIES, SCHEDULE_KINDS
from app.writes import ApplyError, apply_proposal, discard_proposal

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"
llm = OpenAICompatibleClient()


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.warmup_on_start:
        # 기동을 막지 않도록 백그라운드에서 프롬프트 캐시를 예열한다. 실패해도 서비스는 뜬다.
        async def warm():
            try:
                await llm.warmup(SYSTEM_PROMPT)
            except Exception:  # noqa: BLE001
                pass
        asyncio.create_task(warm())
    yield


app = FastAPI(title="Annie - Work Assistant Agent", lifespan=lifespan)


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    session_id: str | None = None
    history: list[dict] = Field(default_factory=list)
    screen_case_id: str | None = None  # 사용자가 보고 있는 화면의 사건. 권한은 여전히 토큰 기준이다.
    persist: bool = True  # 점검용 호출은 False 로 보내 남의 대화 기록에 쌓이지 않게 한다.


class LoginRequest(BaseModel):
    emp_id: str


@app.get("/api/demo/users")
def demo_users():
    with db.session() as conn:
        return db.rows(conn.execute("SELECT emp_id, name, title, branch FROM employee ORDER BY emp_id"))


@app.post("/api/login")
def login(body: LoginRequest):
    # 데모용 로그인. 실제 서비스에서는 사내 SSO 토큰을 검증하는 자리다.
    with db.session() as conn:
        row = conn.execute("SELECT name FROM employee WHERE emp_id = ?", (body.emp_id,)).fetchone()
    if not row:
        raise HTTPException(404, "없는 사용자입니다.")
    return {"token": auth.issue_token(body.emp_id), "name": row["name"]}


@app.get("/api/meta")
def meta():
    # 화면의 선택지도 서버 상수에서 받는다. 화면과 에이전트가 같은 목록을 보게 하기 위해서다.
    return {"schedule_kinds": SCHEDULE_KINDS, "assigned_roles": ASSIGNED_ROLES, "categories": CASE_CATEGORIES}


@app.get("/api/briefing")
def briefing(emp_id: str = Depends(auth.current_emp_id)):
    with db.session() as conn:
        return {"today": clock.today().isoformat(), "items": build_briefing(conn, emp_id)}


@app.get("/api/cases/{case_id}")
def case_detail(case_id: str, emp_id: str = Depends(auth.current_emp_id)):
    with db.session() as conn:
        res = tools_read.get_case_overview(conn, emp_id, case_id)
    if "error" in res:
        raise HTTPException(404, NOT_FOUND)
    return res["case"]


@app.post("/api/ask")
async def ask(body: AskRequest, emp_id: str = Depends(auth.current_emp_id)):
    with db.session() as conn:
        user = conn.execute("SELECT name FROM employee WHERE emp_id = ?", (emp_id,)).fetchone()
    if not user:
        raise HTTPException(401, "로그인이 필요합니다.")
    session_id = body.session_id or uuid.uuid4().hex[:12]
    user_message = build_user_message(body.question, user["name"], clock.today().isoformat(), body.screen_case_id)

    async def events():
        yield _sse({"stage": "session", "session_id": session_id})
        final = None
        async for ev in run_agent(question=body.question, user_message=user_message, emp_id=emp_id,
                                  history=body.history, llm=llm, open_conn=db.session):
            if ev.get("stage") == "done":
                final = ev
            yield _sse(ev)
        if final and body.persist:
            try:
                with db.session() as conn:
                    history.save_turn(conn, emp_id, session_id, body.question, final["answer"])
            except Exception:  # noqa: BLE001 — 답은 이미 화면에 갔다. 보관 실패로 응답을 깨지 않는다.
                pass

    # 리버스 프록시가 기본으로 버퍼링하면 SSE 가 끝날 때까지 화면에 안 보인다.
    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/sessions")
def sessions(emp_id: str = Depends(auth.current_emp_id)):
    with db.session() as conn:
        return history.list_sessions(conn, emp_id)


@app.get("/api/sessions/{session_id}")
def session_detail(session_id: str, emp_id: str = Depends(auth.current_emp_id)):
    with db.session() as conn:
        return history.get_session(conn, emp_id, session_id)


@app.post("/api/proposals/{proposal_id}/apply")
def apply(proposal_id: str, emp_id: str = Depends(auth.current_emp_id)):
    with db.session() as conn:
        try:
            return {"ok": True, "result": apply_proposal(conn, emp_id, proposal_id)}
        except ApplyError as e:
            raise HTTPException(400, str(e))


@app.post("/api/proposals/{proposal_id}/discard")
def discard(proposal_id: str, emp_id: str = Depends(auth.current_emp_id)):
    with db.session() as conn:
        discard_proposal(conn, emp_id, proposal_id)
    return {"ok": True}


@app.get("/")
def index():
    return FileResponse(FRONTEND / "index.html")


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
