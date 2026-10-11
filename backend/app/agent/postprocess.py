"""답변 뒤에 붙는 화면 요소: 출처(바로가기), 선택 버튼, 쓰기 제안 카드.

전부 도구가 돌려준 원본에서 만든다. 모델이 쓴 문장에서 뽑지 않는다.
"""
from app.agent.visibility import case_is_visible

MAX_CHOICES = 8


def build_extras(conn, emp_id: str, executed: list[dict]) -> dict:
    return {
        "sources": _sources(conn, emp_id, executed),
        "choices": _choices(executed),
        "proposals": [e["result"] for e in executed if "proposal_id" in e["result"]],
    }


def _sources(conn, emp_id, executed) -> list[dict]:
    ids: list[str] = []
    for e in executed:
        res = e["result"]
        if "error" in res:
            continue
        cid = e["args"].get("case_id") or res.get("case_id") or (res.get("case") or {}).get("case_id")
        if cid and cid not in ids:
            ids.append(cid)
    out = []
    for cid in ids:
        # 바로가기도 가시성 검사를 통과한 사건만 만든다.
        if not case_is_visible(conn, emp_id, cid):
            continue
        title = conn.execute("SELECT title FROM legal_case WHERE case_id = ?", (cid,)).fetchone()["title"]
        out.append({"case_id": cid, "title": title, "url": f"/cases/{cid}"})
    return out


def _choices(executed) -> dict | None:
    """후보가 여럿이면 모델에게 목록을 적게 하지 않고 원본 목록을 선택 버튼으로 올린다.

    모델이 적으면 이름만 나열돼 고를 수가 없다. 사건 선택과 처분권자 선택이 동시에 뜨면
    무엇을 고르라는 건지 알 수 없으므로, 사건 선택이 있으면 처분권자 선택은 띄우지 않는다.
    """
    case_pick = auth_pick = None
    for e in executed:
        res = e["result"]
        if e["name"] == "find_cases" and res.get("count", 0) >= 2:
            case_pick = {
                "type": "case",
                "options": [{"id": c["case_id"],
                             "label": f"{c['client_name']} · {c['title']} ({c['status']})"}
                            for c in res["cases"][:MAX_CHOICES]],
            }
        if e["name"] == "find_authorities" and res.get("count", 0) >= 2:
            auth_pick = {
                "type": "authority",
                "options": [{"id": a["auth_id"], "label": f"{a['org']} {a['name']} {a['title']}"}
                            for a in res["authorities"][:MAX_CHOICES]],
            }
    return case_pick or auth_pick
