"""도구 결과를 좁은 컨텍스트 창에 맞게 줄인다.

토크나이저를 따로 싣지 않고 한글/ASCII 비율로 보수적으로(실제보다 크게) 추정한다.
줄이는 순서: 긴 텍스트 필드를 먼저 자르고, 그래도 넘치면 목록을 뒤에서부터 자르되
몇 건을 줄였는지 결과에 남긴다. 통째로 버리면 모델이 "없다"로 읽어 버리기 때문이다.
"""
import copy
import json

LONG_TEXT_LIMIT = 200


def estimate_tokens(text: str) -> int:
    hangul = sum(1 for ch in text if "가" <= ch <= "힣")
    other = len(text) - hangul
    # 한글은 대체로 글자당 1토큰 이상, 그 외는 3~4글자당 1토큰. 넉넉하게 잡는다.
    return int(hangul * 1.2 + other / 3) + 1


def _truncate_texts(node, limit: int):
    if isinstance(node, dict):
        return {k: _truncate_texts(v, limit) for k, v in node.items()}
    if isinstance(node, list):
        return [_truncate_texts(v, limit) for v in node]
    if isinstance(node, str) and len(node) > limit:
        return node[:limit] + "…(생략)"
    return node


def _longest_list(node, path=()):
    best = (0, None)
    if isinstance(node, dict):
        for k, v in node.items():
            cand = _longest_list(v, path + (k,))
            if cand[0] > best[0]:
                best = cand
    elif isinstance(node, list) and len(node) > best[0]:
        best = (len(node), path)
    return best


def shrink(result: dict, budget_tokens: int) -> str:
    text = json.dumps(result, ensure_ascii=False)
    if estimate_tokens(text) <= budget_tokens:
        return text

    data = _truncate_texts(copy.deepcopy(result), LONG_TEXT_LIMIT)
    text = json.dumps(data, ensure_ascii=False)
    while estimate_tokens(text) > budget_tokens:
        size, path = _longest_list(data)
        if not path or size <= 1:
            break
        parent = data
        for key in path[:-1]:
            parent = parent[key]
        key = path[-1]
        keep = max(1, size // 2)
        dropped = size - keep
        parent[key] = parent[key][:keep]
        parent[f"{key}_omitted"] = parent.get(f"{key}_omitted", 0) + dropped
        parent["_note"] = "결과가 길어 일부만 보여 줍니다. 생략된 항목은 '없는' 것이 아닙니다."
        text = json.dumps(data, ensure_ascii=False)
    return text
