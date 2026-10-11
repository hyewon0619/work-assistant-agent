"""자연어 질문에서 사건 검색어를 뽑는다.

질문을 통째로 LIKE 에 넣으면 거의 맞지 않는다("김민수 의뢰인 사건 처분권자 등록했나?").
공백·괄호·문장부호로 자르고, 조사와 업무 상투어를 걷어낸 뒤 2글자 이상 조각만 남긴다.
각 조각으로 따로 찾고 합치는 쪽이 임베딩 검색보다 정확했다. 사건 정보는 관계형 DB 에
정규화되어 있어서, 유사도보다 정확한 일치가 맞는 문제였다.
"""
import re

PARTICLES = sorted(
    ["에서", "으로", "한테", "께서", "이랑", "랑", "은", "는", "이", "가", "을", "를",
     "의", "에", "로", "와", "과", "도", "만", "님", "씨"],
    key=len, reverse=True,
)
STOPWORDS = {
    "사건", "의뢰인", "고객", "관련", "알려줘", "알려", "줘", "했나", "했어", "됐어", "등록",
    "확인", "언제", "뭐야", "있어", "있나", "좀", "내", "제", "다음", "일정", "기일", "면담",
    "처분권자", "담당자", "담당", "변호사", "결과", "금액", "계약", "얼마", "몇", "건",
}
# 서술어로 끝나는 조각("등록했나", "알려줄래")은 검색어가 아니다.
VERB_ENDINGS = ("했나", "했어", "했니", "해줘", "됐나", "됐어", "줘", "줄래", "나요", "어요", "까요", "인가", "이야", "야", "니", "할", "해", "하고", "싶어", "주세요")
_SPLIT = re.compile(r"[\s\(\)\[\]{}<>,.!?·/\"'“”‘’~]+")


def _strip_particle(token: str) -> str:
    for p in PARTICLES:
        if token.endswith(p) and len(token) - len(p) >= 2:
            return token[: -len(p)]
    return token


def keywords(text: str) -> list[str]:
    out: list[str] = []
    for raw in _SPLIT.split(text or ""):
        token = _strip_particle(raw.strip())
        if len(token) < 2 or token in STOPWORDS or token.endswith(VERB_ENDINGS):
            continue
        if token not in out:
            out.append(token)
    return out[:6]
