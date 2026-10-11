"""사건 단위 요약 서비스 자리.

운영에서는 사건 하나를 범위로 도는 기존 사건 단위 에이전트가 따로 있었고,
이 에이전트는 그 요약을 도구로 불러 재사용했다. 공개본에서는 같은 자리를
결정적인 요약 함수로 대신한다. 이 함수는 권한 검사를 하지 않으므로 반드시
가시성 검사를 통과한 뒤에만 부른다(tools_read.get_case_summary).
"""
from app import clock


def summarize(conn, case_id: str) -> str:
    case = conn.execute(
        "SELECT c.title, c.category, c.status, c.opened_at, c.result, cl.name AS client_name "
        "FROM legal_case c JOIN client cl ON cl.client_id = c.client_id WHERE c.case_id = ?",
        (case_id,),
    ).fetchone()
    last = conn.execute(
        "SELECT at, content FROM meeting WHERE case_id = ? ORDER BY at DESC LIMIT 1", (case_id,)
    ).fetchone()
    nxt = conn.execute(
        "SELECT kind, at FROM schedule WHERE case_id = ? AND at >= ? ORDER BY at LIMIT 1",
        (case_id, clock.today().isoformat()),
    ).fetchone()

    parts = [f"{case['client_name']} 의뢰인의 {case['category']} 사건({case['title']}), {case['opened_at']} 수임, 현재 {case['status']}."]
    if case["result"]:
        parts.append(f"종결 결과: {case['result']}.")
    if last:
        parts.append(f"최근 면담({last['at'][:10]}): {last['content'][:80]}")
    if nxt:
        parts.append(f"다음 일정: {nxt['kind']} {nxt['at'].replace('T', ' ')}.")
    return " ".join(parts)
