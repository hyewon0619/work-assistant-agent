"""도구 스키마와 실행.

JSON Schema 를 모델에 주더라도 실행부에서 인자를 다시 조인다. 작은 모델은 숫자를 비우거나
문자열로 주고, enum 밖의 값을 지어내기도 한다. 그래서 정수 캐스팅, 범위 클램프,
enum 화이트리스트를 여기서 한 번 더 건다. 필수값이 빠지면 추측하지 말고 되물으라는 오류를 돌려준다.
"""
import json
from dataclasses import dataclass, field
from typing import Any, Callable

from app.agent import tools_read as r
from app.agent import tools_write as w
from app.constants import CASE_CATEGORIES, CASE_STATUSES, SCHEDULE_KINDS


class ArgError(Exception):
    pass


@dataclass
class Param:
    type: str  # "string" | "integer" | "boolean"
    description: str
    required: bool = False
    enum: tuple | None = None
    minimum: int | None = None
    maximum: int | None = None
    default: Any = None


@dataclass
class Tool:
    name: str
    description: str
    fn: Callable
    params: dict[str, Param] = field(default_factory=dict)
    writes: bool = False

    def schema(self) -> dict:
        props, required = {}, []
        for name, p in self.params.items():
            prop: dict = {"type": p.type, "description": p.description}
            if p.enum:
                prop["enum"] = list(p.enum)
            props[name] = prop
            if p.required:
                required.append(name)
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {"type": "object", "properties": props, "required": required},
            },
        }

    def coerce(self, raw: dict) -> dict:
        args = {}
        for name, p in self.params.items():
            value = raw.get(name)
            if value in (None, ""):
                if p.required:
                    raise ArgError(f"'{name}' 값이 없습니다. 추측하지 말고 사용자에게 먼저 물어보세요.")
                if p.default is not None:
                    args[name] = p.default
                continue
            if p.type == "integer":
                try:
                    value = int(float(value))
                except (TypeError, ValueError):
                    raise ArgError(f"'{name}' 는 숫자여야 합니다.")
                if p.minimum is not None:
                    value = max(p.minimum, value)
                if p.maximum is not None:
                    value = min(p.maximum, value)
            elif p.type == "boolean":
                value = value if isinstance(value, bool) else str(value).lower() in ("true", "1", "yes")
            else:
                value = str(value).strip()
            if p.enum and value not in p.enum:
                raise ArgError(f"'{name}' 는 {', '.join(p.enum)} 중 하나여야 합니다.")
            args[name] = value
        return args


CASE_ID = Param("string", "사건 ID. find_cases 등 도구 결과에 나온 값만 쓴다.", required=True)

TOOLS: list[Tool] = [
    # ── 사건 찾기
    Tool("find_cases", "의뢰인 이름, 사건명, 법원 사건번호, 사건 유형으로 내가 볼 수 있는 사건을 찾는다.", r.find_cases, {
        "query": Param("string", "사용자 질문에 나온 이름·사건명 등", required=True),
        "status": Param("string", "진행/종결 필터", enum=CASE_STATUSES),
        "limit": Param("integer", "최대 건수", minimum=1, maximum=20, default=10),
    }),
    Tool("find_authorities", "처분권자(담당 검사·수사관·근로감독관 등) 명부에서 이름이나 기관으로 찾는다.", r.find_authorities, {
        "query": Param("string", "이름 또는 기관명", required=True),
        "limit": Param("integer", "최대 건수", minimum=1, maximum=20, default=10),
    }),
    # ── 사건 내용
    Tool("get_case_overview", "사건 기본 정보(의뢰인, 유형, 상태, 수임일, 종결 결과, 계약 금액).", r.get_case_overview, {"case_id": CASE_ID}),
    Tool("get_case_authorities", "사건에 등록된 처분권자와 등록 여부.", r.get_case_authorities, {"case_id": CASE_ID}),
    Tool("get_case_meetings", "사건의 최근 면담 기록.", r.get_case_meetings, {
        "case_id": CASE_ID,
        "limit": Param("integer", "최대 건수", minimum=1, maximum=20, default=5),
    }),
    Tool("get_case_schedules", "사건의 일정(기본은 오늘 이후).", r.get_case_schedules, {
        "case_id": CASE_ID,
        "include_past": Param("boolean", "지난 일정 포함 여부", default=False),
    }),
    Tool("get_case_employees", "사건 담당자와 역할.", r.get_case_employees, {"case_id": CASE_ID}),
    Tool("get_case_summary", "사건 내용 요약(사건 단위 요약 서비스 재사용).", r.get_case_summary, {"case_id": CASE_ID}),
    # ── 전체 훑기
    Tool("list_my_cases", "내가 담당하는 사건 목록과 총 건수. 건수 질문에는 total 을 그대로 쓴다.", r.list_my_cases, {
        "status": Param("string", "진행/종결", enum=CASE_STATUSES, default="진행"),
        "category": Param("string", "사건 유형", enum=CASE_CATEGORIES),
        "limit": Param("integer", "목록 최대 건수", minimum=1, maximum=50, default=20),
    }),
    Tool("list_my_schedules", "내 담당 사건의 다가오는 일정.", r.list_my_schedules, {
        "days_ahead": Param("integer", "오늘부터 며칠 뒤까지", minimum=0, maximum=365, default=7),
        "kind": Param("string", "일정 종류", enum=SCHEDULE_KINDS),
    }),
    # ── 쓰기 제안 (반영은 사용자 확인 후)
    Tool("propose_meeting_note", "면담 기록 추가를 제안한다. 저장은 사용자가 확인해야 된다.", w.propose_meeting_note, {
        "case_id": CASE_ID,
        "content": Param("string", "면담 내용", required=True),
        "at": Param("string", "면담 일시(YYYY-MM-DDTHH:MM). 없으면 지금"),
    }, writes=True),
    Tool("propose_meeting_update", "기존 면담 기록의 일부 칸 수정을 제안한다. 바꿀 칸만 넘긴다.", w.propose_meeting_update, {
        "meeting_id": Param("string", "면담 기록 ID", required=True),
        "content": Param("string", "바꿀 면담 내용"),
        "lawyer_comment": Param("string", "바꿀 변호사 코멘트"),
    }, writes=True),
    Tool("propose_meeting_append", "기존 면담 기록 끝에 덧붙일 내용만 넘긴다. 전문을 다시 쓰지 않는다.", w.propose_meeting_append, {
        "meeting_id": Param("string", "면담 기록 ID", required=True),
        "addition": Param("string", "덧붙일 내용", required=True),
    }, writes=True),
    Tool("propose_authority_link", "사건에 처분권자 등록을 제안한다.", w.propose_authority_link, {
        "case_id": CASE_ID,
        "auth_id": Param("string", "find_authorities 결과의 처분권자 ID", required=True),
    }, writes=True),
    Tool("propose_schedule", "사건 일정 등록을 제안한다.", w.propose_schedule, {
        "case_id": CASE_ID,
        "kind": Param("string", "일정 종류", required=True, enum=SCHEDULE_KINDS),
        "at": Param("string", "일시(YYYY-MM-DDTHH:MM)", required=True),
        "place": Param("string", "장소"),
        "memo": Param("string", "메모"),
    }, writes=True),
]

BY_NAME = {t.name: t for t in TOOLS}


def tool_schemas() -> list[dict]:
    return [t.schema() for t in TOOLS]


def run_tool(conn, emp_id: str, name: str, raw_args: str | dict) -> dict:
    """도구 하나를 실행한다. 어떤 실패도 예외로 올리지 않고 오류 결과로 돌려준다."""
    tool = BY_NAME.get(name)
    if tool is None:
        return {"error": f"'{name}' 라는 도구는 없습니다. 제공된 도구만 쓰세요."}
    try:
        parsed = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
        if not isinstance(parsed, dict):
            raise ArgError("인자는 JSON 객체여야 합니다.")
        args = tool.coerce(parsed)
    except json.JSONDecodeError:
        return {"error": "인자 JSON 을 읽지 못했습니다. 올바른 JSON 으로 다시 호출하세요."}
    except ArgError as e:
        return {"error": str(e)}
    try:
        return tool.fn(conn, emp_id, **args)
    except Exception as e:  # noqa: BLE001 — 모델에게 실패를 보여 주는 것이 목적이다.
        return {"error": f"도구 실행 중 오류가 발생했습니다: {type(e).__name__}"}
