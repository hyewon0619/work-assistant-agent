import os
from datetime import date, datetime, timedelta


def today() -> date:
    # 테스트와 데모 데이터가 같은 기준일을 보도록 고정할 수 있다.
    fixed = os.getenv("FIXED_TODAY")
    return date.fromisoformat(fixed) if fixed else date.today()


def now_iso() -> str:
    return datetime.combine(today(), datetime.now().time()).isoformat(timespec="minutes")


def days_from_today(n: int) -> str:
    return (today() + timedelta(days=n)).isoformat()
