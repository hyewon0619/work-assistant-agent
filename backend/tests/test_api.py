import json

import pytest
from fastapi.testclient import TestClient

from app import auth, main
from app.constants import SCHEDULE_KINDS


@pytest.fixture
def client(monkeypatch, fake_llm):
    def use(rounds):
        monkeypatch.setattr(main, "llm", fake_llm(rounds))
        return TestClient(main.app)
    return use


def headers(emp_id="E001"):
    return {"Authorization": f"Bearer {auth.issue_token(emp_id)}"}


def ask(c, body, emp_id="E001"):
    res = c.post("/api/ask", json=body, headers=headers(emp_id))
    assert res.headers["x-accel-buffering"] == "no"
    return [json.loads(line[5:]) for line in res.text.split("\n\n") if line.startswith("data:")]


def test_requires_login(client):
    c = client([])
    assert c.get("/api/briefing").status_code == 401
    assert c.get("/api/briefing", headers={"Authorization": "Bearer E001.forged"}).status_code == 401


def test_briefing_surfaces_items_first(client):
    items = client([]).get("/api/briefing", headers=headers()).json()["items"]
    texts = " ".join(i["text"] for i in items)
    assert "기일" in texts and "처분권자 미등록" in texts
    assert all(i["action"] for i in items if i["case_id"])
    assert any("더 있음" in i["text"] for i in items)


def test_turn_is_saved_and_isolated_per_user(client):
    c = client(["안녕하세요."])
    events = ask(c, {"question": "안녕"})
    sid = events[0]["session_id"]
    assert c.get(f"/api/sessions/{sid}", headers=headers()).json()[0]["question"] == "안녕"
    assert c.get(f"/api/sessions/{sid}", headers=headers("E002")).json() == []


def test_inspection_calls_are_not_saved(client):
    c = client(["점검 응답"])
    ask(c, {"question": "점검", "persist": False})
    assert c.get("/api/sessions", headers=headers()).json() == []


def test_meta_exposes_shared_constants(client):
    assert tuple(client([]).get("/api/meta").json()["schedule_kinds"]) == SCHEDULE_KINDS


def test_proposal_flow_through_api(client):
    c = client([[("propose_schedule", json.dumps({"case_id": "K00001", "kind": "면담", "at": "2026-10-20T14:00"}))],
                "면담 일정을 제안했습니다. 화면에서 확인을 눌러 주세요."])
    final = next(e for e in ask(c, {"question": "박민수 사기 사건 20일 2시 면담 잡아줘"}) if e.get("stage") == "done")
    pid = final["proposals"][0]["proposal_id"]
    assert c.post(f"/api/proposals/{pid}/apply", headers=headers("E002")).status_code == 400
    assert c.post(f"/api/proposals/{pid}/apply", headers=headers()).json()["ok"]
