"""답변 품질 가드. 전부 결정적 규칙이다."""
import re

# 답변에 사실값(금액·건수·날짜 등)이 있는지 본다.
FACT_PATTERN = re.compile(
    r"\d[\d,]*\s*(원|만원|억|건|명|%|일|회)|\d{4}[-.]\d{1,2}[-.]\d{1,2}|\d{1,2}월\s*\d{1,2}일"
)

# 자체 호스팅 모델이 내부 제어 토큰을 본문에 흘리는 경우가 있었다.
CONTROL_TOKENS = ("<|im_end|>", "<|im_start|>", "<|eot_id|>", "<end_of_turn>", "<start_of_turn>", "<|endoftext|>")

URL_PATTERN = re.compile(r"\[([^\]]+)\]\((?:https?://|/)[^)]*\)|https?://\S+")


def states_facts(text: str) -> bool:
    return bool(FACT_PATTERN.search(text or ""))


def needs_grounding_retry(answer: str, tool_calls_made: int) -> bool:
    """도구를 한 번도 안 부르고 사실값을 말했다면 재시도 대상이다.

    실제로 있었던 사고: 도구 없이 계약 금액을 답했는데 그 값은 DB 에서 비어 있었고,
    이전 답변에 나온 다른 사건의 금액을 보고 지어낸 것이었다.
    """
    return tool_calls_made == 0 and states_facts(answer)


def cut_control_tokens(text: str) -> str:
    """제어 토큰을 지우지 않고 그 앞에서 잘라낸다.

    지우기만 하면 토큰 뒤에 딸려 온 중복 문단이 화면에 그대로 남는다.
    """
    cut = len(text)
    for tok in CONTROL_TOKENS:
        idx = text.find(tok)
        if idx != -1:
            cut = min(cut, idx)
    return text[:cut].rstrip()


def strip_links(text: str) -> str:
    """모델이 쓴 링크·주소는 지운다. 바로가기는 도구가 돌려준 ID 로 서버가 만든다.

    모델이 주소나 번호를 지어내면 엉뚱한 사건으로 가기 때문이다.
    """
    return URL_PATTERN.sub(lambda m: m.group(1) or "", text)
