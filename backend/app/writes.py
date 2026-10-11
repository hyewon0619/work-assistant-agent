"""사용자가 확인한 제안만 실제로 반영한다. 에이전트 루프에서는 이 모듈을 부르지 않는다."""
import json
import uuid

from app.agent.visibility import case_is_visible


class ApplyError(Exception):
    pass


def apply_proposal(conn, emp_id: str, proposal_id: str) -> dict:
    p = conn.execute(
        "SELECT * FROM proposal WHERE proposal_id = ? AND emp_id = ?", (proposal_id, emp_id)
    ).fetchone()
    if not p:
        raise ApplyError("제안을 찾을 수 없습니다.")
    if p["status"] != "pending":
        raise ApplyError("이미 처리된 제안입니다.")
    # 제안을 만든 뒤 권한이 바뀌었을 수 있으므로 반영 시점에 다시 확인한다.
    if not case_is_visible(conn, emp_id, p["case_id"]):
        raise ApplyError("해당 사건을 찾을 수 없습니다.")

    payload = json.loads(p["payload"])
    handler = _HANDLERS[p["kind"]]
    result = handler(conn, emp_id, p["case_id"], payload)
    conn.execute("UPDATE proposal SET status = 'applied' WHERE proposal_id = ?", (proposal_id,))
    conn.commit()
    return result


def discard_proposal(conn, emp_id: str, proposal_id: str) -> None:
    conn.execute(
        "UPDATE proposal SET status = 'discarded' WHERE proposal_id = ? AND emp_id = ? AND status = 'pending'",
        (proposal_id, emp_id),
    )
    conn.commit()


def _meeting_note(conn, emp_id, case_id, payload):
    meeting_id = uuid.uuid4().hex[:12]
    conn.execute(
        "INSERT INTO meeting (meeting_id, case_id, at, author_emp_id, content) VALUES (?, ?, ?, ?, ?)",
        (meeting_id, case_id, payload["at"], emp_id, payload["content"]),
    )
    return {"meeting_id": meeting_id}


def _meeting_update(conn, emp_id, case_id, payload):
    # 기존 CRUD 는 안 넘긴 칸을 None 으로 덮어써서, 면담 내용만 고치려다 변호사 코멘트가 지워졌다.
    # 여기서는 제안에 담긴 칸만 SET 한다.
    fields = {k: v for k, v in payload.items() if k in ("content", "lawyer_comment")}
    sets = ", ".join(f"{k} = :{k}" for k in fields)
    conn.execute(f"UPDATE meeting SET {sets} WHERE meeting_id = :meeting_id",
                 {**fields, "meeting_id": payload["meeting_id"]})
    return {"meeting_id": payload["meeting_id"], "updated": list(fields)}


def _meeting_append(conn, emp_id, case_id, payload):
    row = conn.execute("SELECT content FROM meeting WHERE meeting_id = ?", (payload["meeting_id"],)).fetchone()
    merged = row["content"].rstrip() + "\n" + payload["addition"].strip()
    conn.execute("UPDATE meeting SET content = ? WHERE meeting_id = ?", (merged, payload["meeting_id"]))
    return {"meeting_id": payload["meeting_id"]}


def _authority_link(conn, emp_id, case_id, payload):
    conn.execute("INSERT OR IGNORE INTO case_authority (case_id, auth_id) VALUES (?, ?)",
                 (case_id, payload["auth_id"]))
    return {"case_id": case_id, "auth_id": payload["auth_id"]}


def _schedule(conn, emp_id, case_id, payload):
    sched_id = uuid.uuid4().hex[:12]
    conn.execute(
        "INSERT INTO schedule (sched_id, case_id, kind, at, place, memo) VALUES (?, ?, ?, ?, ?, ?)",
        (sched_id, case_id, payload["kind"], payload["at"], payload.get("place"), payload.get("memo")),
    )
    return {"sched_id": sched_id}


_HANDLERS = {
    "meeting_note": _meeting_note,
    "meeting_update": _meeting_update,
    "meeting_append": _meeting_append,
    "authority_link": _authority_link,
    "schedule": _schedule,
}
