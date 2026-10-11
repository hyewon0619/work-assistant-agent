"""권한 경계. 에이전트가 사건 데이터에 닿는 모든 경로는 이 모듈의 절을 거친다.

사건 단위 에이전트는 URL 의 사건 ID 가 울타리였지만, 이 에이전트는 사건을 고르지 않고 시작한다.
도구마다 따로 판단하면 한 군데만 빠져도 남의 사건이 샌다. 그래서 규칙을 여기 한 곳에 모은다.

원칙
1. emp_id 는 로그인 토큰에서만 온다. 도구 스키마에 emp_id 가 없다.
2. 사건 ID 를 이미 아는 조회에도 예외 없이 가시성 절을 건다.
   모델은 앞 답변에서 본 ID 를 다음 질문에 그대로 쓰므로, "ID 를 알면 볼 수 있다"가 되면 안 된다.
3. 권한 밖 접근은 "없는 사건"과 같은 문구로 막는다.
   "권한이 없습니다"는 그 사건이 존재한다는 사실을 알려 주는 셈이다.
4. "조회 가능"과 "내가 담당"을 다른 절로 둔다. 건수를 셀 때는 담당 절을 쓴다.
   콘솔 화면과 숫자가 갈리면 사용자가 무엇을 믿을지 모른다.

모든 절은 sqlite 이름 있는 자리표시자를 쓰고, :emp_id 는 scope() 로만 채운다.
"""
from app.constants import ALL_MEMBER_ROLES, ASSIGNED_ROLES

NOT_FOUND = "해당 사건을 찾을 수 없습니다."


def _roles(prefix: str, roles) -> tuple[str, dict]:
    names = [f"{prefix}{i}" for i in range(len(roles))]
    return ",".join(f":{n}" for n in names), dict(zip(names, roles))


def visible_clause(alias: str = "c") -> tuple[str, dict]:
    """조회 가능한 사건: 구성원으로 등록된 사건(열람 포함)."""
    marks, params = _roles("vr", ALL_MEMBER_ROLES)
    sql = (
        f"EXISTS (SELECT 1 FROM case_member vm WHERE vm.case_id = {alias}.case_id "
        f"AND vm.emp_id = :emp_id AND vm.role IN ({marks}))"
    )
    return sql, params


def assigned_clause(alias: str = "c") -> tuple[str, dict]:
    """내가 담당하는 사건: 담당 역할로 등록된 사건만. 건수 집계에 쓴다."""
    marks, params = _roles("ar", ASSIGNED_ROLES)
    sql = (
        f"EXISTS (SELECT 1 FROM case_member am WHERE am.case_id = {alias}.case_id "
        f"AND am.emp_id = :emp_id AND am.role IN ({marks}))"
    )
    return sql, params


def scope(emp_id: str, *clause_params: dict, **extra) -> dict:
    """절 파라미터와 emp_id 를 합친다. emp_id 를 넣는 곳은 여기뿐이다."""
    merged: dict = {}
    for p in clause_params:
        merged.update(p)
    merged.update(extra)
    merged["emp_id"] = emp_id
    return merged


def case_is_visible(conn, emp_id: str, case_id: str) -> bool:
    clause, params = visible_clause("c")
    sql = f"SELECT 1 FROM legal_case c WHERE c.case_id = :case_id AND {clause}"
    return conn.execute(sql, scope(emp_id, params, case_id=case_id)).fetchone() is not None
