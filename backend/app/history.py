"""대화 기록.

턴(질문+답변 쌍) 단위로 보관하고, emp_{id} 를 방 키로 그 안을 세션으로 나눈다.
"새 대화"는 기존 기록을 지우지 않고 새 세션을 연다. 지우면 기록 목록이 비기 때문이다.
세션 제목은 첫 질문을 그대로 쓴다. 요약 제목을 만들려면 모델을 한 번 더 불러야 하는데,
그게 첫 질문보다 낫다는 보장이 없다.
"""
from app import clock
from app.db import rows


def room_key(emp_id: str) -> str:
    return f"emp_{emp_id}"


def save_turn(conn, emp_id: str, session_id: str, question: str, answer: str) -> None:
    conn.execute(
        "INSERT INTO chat_turn (room_key, session_id, question, answer, created_at) VALUES (?, ?, ?, ?, ?)",
        (room_key(emp_id), session_id, question, answer, clock.now_iso()),
    )
    conn.commit()


def list_sessions(conn, emp_id: str) -> list[dict]:
    return rows(conn.execute(
        "SELECT session_id, MIN(created_at) AS started_at, "
        "(SELECT question FROM chat_turn t2 WHERE t2.room_key = t.room_key AND t2.session_id = t.session_id "
        " ORDER BY turn_id LIMIT 1) AS title "
        "FROM chat_turn t WHERE room_key = ? GROUP BY session_id ORDER BY started_at DESC",
        (room_key(emp_id),),
    ))


def get_session(conn, emp_id: str, session_id: str) -> list[dict]:
    # 방 키로 먼저 거른다. 세션 ID 만 알면 남의 대화를 볼 수 있게 되면 안 된다.
    return rows(conn.execute(
        "SELECT question, answer, created_at FROM chat_turn WHERE room_key = ? AND session_id = ? ORDER BY turn_id",
        (room_key(emp_id), session_id),
    ))
