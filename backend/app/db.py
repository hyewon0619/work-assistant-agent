import sqlite3
from contextlib import contextmanager
from pathlib import Path

from app.config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS employee (
    emp_id   TEXT PRIMARY KEY,
    name     TEXT NOT NULL,
    title    TEXT NOT NULL,
    branch   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS client (
    client_id TEXT PRIMARY KEY,
    name      TEXT NOT NULL,
    kind      TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS legal_case (
    case_id         TEXT PRIMARY KEY,
    court_no        TEXT,
    title           TEXT NOT NULL,
    category        TEXT NOT NULL,
    client_id       TEXT NOT NULL REFERENCES client(client_id),
    branch          TEXT NOT NULL,
    status          TEXT NOT NULL,
    opened_at       TEXT NOT NULL,
    closed_at       TEXT,
    result          TEXT,
    contract_amount INTEGER
);
CREATE TABLE IF NOT EXISTS case_member (
    case_id TEXT NOT NULL REFERENCES legal_case(case_id),
    emp_id  TEXT NOT NULL REFERENCES employee(emp_id),
    role    TEXT NOT NULL,
    PRIMARY KEY (case_id, emp_id, role)
);
CREATE TABLE IF NOT EXISTS authority (
    auth_id TEXT PRIMARY KEY,
    name    TEXT NOT NULL,
    org     TEXT NOT NULL,
    title   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS case_authority (
    case_id TEXT NOT NULL REFERENCES legal_case(case_id),
    auth_id TEXT NOT NULL REFERENCES authority(auth_id),
    PRIMARY KEY (case_id, auth_id)
);
CREATE TABLE IF NOT EXISTS schedule (
    sched_id TEXT PRIMARY KEY,
    case_id  TEXT NOT NULL REFERENCES legal_case(case_id),
    kind     TEXT NOT NULL,
    at       TEXT NOT NULL,
    place    TEXT,
    memo     TEXT
);
CREATE TABLE IF NOT EXISTS meeting (
    meeting_id     TEXT PRIMARY KEY,
    case_id        TEXT NOT NULL REFERENCES legal_case(case_id),
    at             TEXT NOT NULL,
    author_emp_id  TEXT NOT NULL,
    content        TEXT NOT NULL,
    lawyer_comment TEXT
);
CREATE TABLE IF NOT EXISTS proposal (
    proposal_id TEXT PRIMARY KEY,
    emp_id      TEXT NOT NULL,
    kind        TEXT NOT NULL,
    case_id     TEXT NOT NULL,
    payload     TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chat_turn (
    turn_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    room_key   TEXT NOT NULL,
    session_id TEXT NOT NULL,
    question   TEXT NOT NULL,
    answer     TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_member_emp ON case_member(emp_id);
CREATE INDEX IF NOT EXISTS ix_sched_case ON schedule(case_id, at);
CREATE INDEX IF NOT EXISTS ix_turn_room ON chat_turn(room_key, session_id);
"""


def connect(path: Path | None = None) -> sqlite3.Connection:
    path = Path(path or settings.db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


@contextmanager
def session(path: Path | None = None):
    # 요청마다 짧게 열고 닫는다. 스트리밍 응답이 길어지는 동안 커넥션을 붙잡지 않기 위해서다.
    conn = connect(path)
    try:
        yield conn
    finally:
        conn.close()


def rows(cur) -> list[dict]:
    return [dict(r) for r in cur.fetchall()]
