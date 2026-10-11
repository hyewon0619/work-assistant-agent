"""데모용 로그인 토큰.

에이전트 권한의 출발점은 오직 이 토큰이다. emp_id 를 요청 본문이나 도구 인자로 받지 않는다.
모델이 고른 값이 권한이 되면 안 되기 때문이다.

이 의존성은 서명만 검증하고 DB 를 열지 않는다. 응답 스트림이 길어지는 동안
DB 커넥션이 인증 단계에 묶여 있지 않도록 가볍게 둔다.
"""
import base64
import hashlib
import hmac

from fastapi import Header, HTTPException

from app.config import settings


def _sign(emp_id: str) -> str:
    mac = hmac.new(settings.token_secret.encode(), emp_id.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac).decode().rstrip("=")


def issue_token(emp_id: str) -> str:
    return f"{emp_id}.{_sign(emp_id)}"


def verify_token(token: str) -> str | None:
    emp_id, _, sig = token.partition(".")
    if not emp_id or not sig:
        return None
    return emp_id if hmac.compare_digest(sig, _sign(emp_id)) else None


def current_emp_id(authorization: str = Header(default="")) -> str:
    token = authorization.removeprefix("Bearer ").strip()
    emp_id = verify_token(token)
    if not emp_id:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    return emp_id
