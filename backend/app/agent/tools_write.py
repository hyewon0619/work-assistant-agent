"""쓰기 "제안" 도구. 모델은 DB 를 직접 고치지 못한다.

여기 도구들은 proposal 행만 만든다. 실제 반영은 사용자가 화면의 제안 카드에서 확인을 누른 뒤
별도 엔드포인트(/api/proposals/{id}/apply → app.writes)로만 들어온다.
읽기는 틀려도 다시 물으면 되지만, 쓰기는 틀리면 되돌려야 하기 때문이다.

읽기 도구와 파일을 나눈 것도 의도다. 조회 도구가 늘어나다 실수로 쓰기 경로를 끌어 쓰는 일을 막는다.
"""
import json
import uuid

from app import clock
from app.agent.visibility import NOT_FOUND, case_is_visible


def _create(conn, emp_id: str, kind: str, case_id: str, payload: dict, preview: str) -> dict:
    proposal_id = uuid.uuid4().hex[:12]
    conn.execute(
        "INSERT INTO proposal (proposal_id, emp_id, kind, case_id, payload, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, 'pending', ?)",
        (proposal_id, emp_id, kind, case_id, json.dumps(payload, ensure_ascii=False), clock.now_iso()),
    )
    conn.commit()
    return {
        "proposal_id": proposal_id,
        "kind": kind,
        "case_id": case_id,
        "preview": preview,
        "note": "아직 반영되지 않았습니다. 사용자가 화면에서 확인해야 저장됩니다.",
    }


def _meeting_case(conn, meeting_id: str) -> str | None:
    row = conn.execute("SELECT case_id FROM meeting WHERE meeting_id = ?", (meeting_id,)).fetchone()
    return row["case_id"] if row else None


def propose_meeting_note(conn, emp_id, case_id: str, content: str, at: str | None = None):
    if not case_is_visible(conn, emp_id, case_id):
        return {"error": NOT_FOUND}
    payload = {"content": content, "at": at or clock.now_iso()}
    return _create(conn, emp_id, "meeting_note", case_id, payload, f"면담 기록 추가: {content[:60]}")


def propose_meeting_update(conn, emp_id, meeting_id: str, content: str | None = None,
                           lawyer_comment: str | None = None):
    case_id = _meeting_case(conn, meeting_id)
    if not case_id or not case_is_visible(conn, emp_id, case_id):
        return {"error": "해당 면담 기록을 찾을 수 없습니다."}
    # 넘어온 칸만 담는다. 반영할 때도 이 칸만 바꾼다(app.writes 참고).
    payload = {"meeting_id": meeting_id}
    if content is not None:
        payload["content"] = content
    if lawyer_comment is not None:
        payload["lawyer_comment"] = lawyer_comment
    if len(payload) == 1:
        return {"error": "고칠 내용이 없습니다. 무엇을 바꿀지 사용자에게 먼저 물어보세요."}
    return _create(conn, emp_id, "meeting_update", case_id, payload, "면담 기록 수정")


def propose_meeting_append(conn, emp_id, meeting_id: str, addition: str):
    # "한 줄 더 추가해줘"는 전문을 다시 쓰게 하지 않고 추가분만 받는다.
    # 모델이 전문을 옮겨 적다 문단을 한 번 더 복사하는 일이 실제로 있었다. 합치는 건 서버가 한다.
    case_id = _meeting_case(conn, meeting_id)
    if not case_id or not case_is_visible(conn, emp_id, case_id):
        return {"error": "해당 면담 기록을 찾을 수 없습니다."}
    return _create(conn, emp_id, "meeting_append", case_id,
                   {"meeting_id": meeting_id, "addition": addition}, f"면담 기록에 추가: {addition[:60]}")


def propose_authority_link(conn, emp_id, case_id: str, auth_id: str):
    if not case_is_visible(conn, emp_id, case_id):
        return {"error": NOT_FOUND}
    auth = conn.execute("SELECT name, org FROM authority WHERE auth_id = ?", (auth_id,)).fetchone()
    if not auth:
        return {"error": "해당 처분권자를 찾을 수 없습니다. find_authorities 로 먼저 찾으세요."}
    return _create(conn, emp_id, "authority_link", case_id, {"auth_id": auth_id},
                   f"처분권자 등록: {auth['org']} {auth['name']}")


def propose_schedule(conn, emp_id, case_id: str, kind: str, at: str,
                     place: str | None = None, memo: str | None = None):
    if not case_is_visible(conn, emp_id, case_id):
        return {"error": NOT_FOUND}
    payload = {"kind": kind, "at": at, "place": place, "memo": memo}
    return _create(conn, emp_id, "schedule", case_id, payload, f"일정 등록: {kind} {at.replace('T', ' ')}")
