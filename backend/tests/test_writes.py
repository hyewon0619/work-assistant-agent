import pytest

from app.agent import tools_write as w
from app.writes import ApplyError, apply_proposal


def _meeting(conn, emp_id="E001"):
    return conn.execute(
        "SELECT m.* FROM meeting m JOIN case_member cm ON cm.case_id = m.case_id "
        "WHERE cm.emp_id = ? AND m.lawyer_comment IS NOT NULL LIMIT 1", (emp_id,),
    ).fetchone()


def test_proposal_does_not_touch_data_until_applied(conn):
    before = conn.execute("SELECT COUNT(*) FROM schedule").fetchone()[0]
    p = w.propose_schedule(conn, "E001", "K00001", "면담", "2026-10-20T14:00")
    assert conn.execute("SELECT COUNT(*) FROM schedule").fetchone()[0] == before
    apply_proposal(conn, "E001", p["proposal_id"])
    assert conn.execute("SELECT COUNT(*) FROM schedule").fetchone()[0] == before + 1


def test_partial_update_keeps_other_fields(conn):
    m = _meeting(conn)
    p = w.propose_meeting_update(conn, "E001", m["meeting_id"], content="내용만 수정")
    apply_proposal(conn, "E001", p["proposal_id"])
    after = conn.execute("SELECT * FROM meeting WHERE meeting_id = ?", (m["meeting_id"],)).fetchone()
    assert after["content"] == "내용만 수정"
    assert after["lawyer_comment"] == m["lawyer_comment"]


def test_append_is_merged_by_server(conn):
    m = _meeting(conn)
    p = w.propose_meeting_append(conn, "E001", m["meeting_id"], "의뢰인에게 서류 목록 문자 발송")
    apply_proposal(conn, "E001", p["proposal_id"])
    content = conn.execute("SELECT content FROM meeting WHERE meeting_id = ?", (m["meeting_id"],)).fetchone()["content"]
    assert content == m["content"].rstrip() + "\n의뢰인에게 서류 목록 문자 발송"


def test_only_owner_can_apply_and_only_once(conn):
    p = w.propose_meeting_note(conn, "E001", "K00001", "전화 상담")
    with pytest.raises(ApplyError):
        apply_proposal(conn, "E002", p["proposal_id"])
    apply_proposal(conn, "E001", p["proposal_id"])
    with pytest.raises(ApplyError):
        apply_proposal(conn, "E001", p["proposal_id"])


def test_cannot_propose_on_invisible_case(conn):
    other = conn.execute(
        "SELECT case_id FROM legal_case WHERE case_id NOT IN (SELECT case_id FROM case_member WHERE emp_id = 'E001') LIMIT 1"
    ).fetchone()["case_id"]
    assert "error" in w.propose_meeting_note(conn, "E001", other, "몰래 쓰기")
