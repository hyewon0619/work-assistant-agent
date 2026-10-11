"""합성 데이터 생성기. 실제 조직·사건·인물 정보는 한 건도 들어 있지 않다.

시드 고정 난수로 직원·의뢰인·사건·일정·면담 기록을 만든다. 날짜는 오늘(또는 FIXED_TODAY)을
기준으로 만들어서 언제 실행해도 "다가오는 일정", "오래 면담 없는 사건" 같은 상황이 생긴다.
데모 사용자(E001)에게는 동명이인 의뢰인, 처분권자 미등록 사건 등 시연용 상황을 일부러 심어 둔다.

    python scripts/generate_data.py
"""
import random
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import clock, db  # noqa: E402
from app.config import settings  # noqa: E402
from app.constants import CASE_CATEGORIES  # noqa: E402

SURNAMES = list("김이박최정강조윤장임한오서신권황안송류홍")
GIVEN = ["민수", "지현", "서연", "도윤", "하은", "준호", "수빈", "예린", "현우", "지민", "유진", "성훈",
         "다은", "태윤", "소연", "재원", "은지", "민재", "가영", "우진", "채원", "동현", "나연", "시우"]
COMPANIES = ["한빛물산", "새솔테크", "푸른유통", "다온건설", "누리식품", "온길로지스", "하람전자", "가온소프트"]
BRANCHES = ["서울", "수원", "부산"]
ORGS = ["서울중앙지방검찰청", "수원지방검찰청", "부산지방검찰청", "서울강남경찰서", "수원남부경찰서",
        "부산해운대경찰서", "서울지방고용노동청", "경기지방고용노동청"]
TITLES_BY_CATEGORY = {
    "형사": ["사기 고소", "업무상 횡령", "명예훼손 고소", "교통사고 처리", "폭행 피의"],
    "이혼": ["협의이혼", "재판상 이혼", "양육권 분쟁", "재산분할 청구"],
    "손해배상": ["교통사고 손해배상", "의료사고 손해배상", "계약 위반 손해배상"],
    "부동산": ["임대차보증금 반환", "명도 소송", "매매대금 청구"],
    "노동": ["부당해고 구제", "임금체불 진정", "산업재해 보상"],
    "상속": ["유류분 반환", "상속재산 분할", "한정승인"],
}
RESULTS = ["승소", "일부 승소", "조정 성립", "불기소", "기소유예", "합의 종결", "패소"]
MEETING_SNIPPETS = [
    "의뢰인이 추가 증거자료를 제출하기로 함", "상대방 측 합의 의사 확인", "다음 기일 전 진술서 초안 공유 예정",
    "의뢰인이 진행 상황에 불안해함, 주 1회 연락 요청", "증인 2명 연락처 확보", "계약서 원본 확인 완료",
    "비용 분할 납부 일정 안내", "의뢰인이 조기 합의를 희망함",
]


def name(rng):
    return rng.choice(SURNAMES) + rng.choice(GIVEN)


def main(path: Path | None = None, seed: int = 7) -> Path:
    rng = random.Random(seed)
    path = Path(path or settings.db_path)
    if path.exists():
        path.unlink()
    conn = db.connect(path)
    db.init_schema(conn)
    today = clock.today()

    def day(offset: int) -> str:
        return (today + timedelta(days=offset)).isoformat()

    def at(offset: int, hour: int) -> str:
        return f"{day(offset)}T{hour:02d}:{rng.choice(['00', '30'])}"

    # ── 직원
    employees = [("E001", "김지현", "변호사", "서울")]
    for i in range(2, 13):
        title = "변호사" if i <= 7 else "사무장" if i <= 10 else "상담원"
        employees.append((f"E{i:03d}", name(rng), title, rng.choice(BRANCHES)))
    conn.executemany("INSERT INTO employee VALUES (?, ?, ?, ?)", employees)
    lawyers = [e[0] for e in employees if e[2] == "변호사"]
    managers = [e[0] for e in employees if e[2] == "사무장"]
    everyone = [e[0] for e in employees]

    # ── 의뢰인 (동명이인 '박민수' 두 명을 일부러 둔다)
    clients = [("C0001", "박민수", "개인"), ("C0002", "박민수", "개인")]
    for i in range(3, 161):
        kind = "기업" if rng.random() < 0.12 else "개인"
        nm = rng.choice(COMPANIES) + ("(주)" if rng.random() < 0.5 else "") if kind == "기업" else name(rng)
        clients.append((f"C{i:04d}", nm, kind))
    conn.executemany("INSERT INTO client VALUES (?, ?, ?)", clients)

    # ── 처분권자 명부
    authorities = []
    for i in range(1, 31):
        org = rng.choice(ORGS)
        title = "근로감독관" if "고용노동" in org else "수사관" if "경찰" in org else "검사"
        authorities.append((f"A{i:03d}", name(rng), org, title))
    conn.executemany("INSERT INTO authority VALUES (?, ?, ?, ?)", authorities)

    # ── 사건
    cases, members, links, schedules, meetings = [], [], [], [], []
    for i in range(1, 321):
        case_id = f"K{i:05d}"
        client_id = clients[i % len(clients)][0] if i > 2 else clients[i - 1][0]
        category = rng.choice(CASE_CATEGORIES)
        opened = -rng.randint(10, 540)
        closed = rng.random() < 0.35 and opened < -60
        status = "종결" if closed else "진행"
        amount = int(rng.lognormvariate(15.6, 0.6) // 100000 * 100000)
        court_no = f"20{rng.randint(23, 25)}{rng.choice(['가단', '가합', '드단', '고단', '구합'])}{rng.randint(1000, 99999)}"
        cases.append((case_id, court_no, rng.choice(TITLES_BY_CATEGORY[category]), category, client_id,
                      rng.choice(BRANCHES), status, day(opened), day(opened + rng.randint(40, -opened)) if closed else None,
                      rng.choice(RESULTS) if closed else None, amount))

        lead = "E001" if i % 9 == 0 or i <= 2 else rng.choice(lawyers)
        members.append((case_id, lead, "주담당변호사"))
        if rng.random() < 0.4:
            members.append((case_id, rng.choice([l for l in lawyers if l != lead]), "담당변호사"))
        members.append((case_id, rng.choice(managers), "사무장"))
        if rng.random() < 0.15:
            viewer = rng.choice(everyone)
            if viewer not in (lead,):
                members.append((case_id, viewer, "열람"))

        if category in ("형사", "노동") and rng.random() < 0.6:
            links.append((case_id, rng.choice(authorities)[0]))

        for j in range(rng.randint(0, 4)):
            offset = rng.randint(-60, 45) if status == "진행" else rng.randint(-200, -1)
            schedules.append((f"S{i:05d}{j}", case_id, rng.choice(["기일", "면담", "제출기한", "상담"]),
                              at(offset, rng.randint(9, 17)), rng.choice(["본사 3층", "법원", "화상", None]), None))
        for j in range(rng.randint(0, 5)):
            offset = rng.randint(opened, -1)
            meetings.append((f"M{i:05d}{j}", case_id, at(offset, rng.randint(9, 18)), lead,
                             rng.choice(MEETING_SNIPPETS), "다음 기일 전 재확인 필요" if rng.random() < 0.3 else None))

    # ── 데모 사용자 시연용 상황
    schedules.append(("S_DEMO1", "K00001", "기일", at(1, 10), "서울중앙지방법원 351호", "증인신문"))
    schedules.append(("S_DEMO2", "K00002", "면담", at(2, 15), "본사 3층", None))
    cases[0] = cases[0][:2] + ("사기 고소", "형사") + cases[0][4:6] + ("진행", cases[0][7], None, None, 25_000_000)
    links[:] = [l for l in links if l[0] != "K00001"]

    conn.executemany("INSERT INTO legal_case VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", cases)
    conn.executemany("INSERT OR IGNORE INTO case_member VALUES (?, ?, ?)", members)
    conn.executemany("INSERT OR IGNORE INTO case_authority VALUES (?, ?)", links)
    conn.executemany("INSERT INTO schedule VALUES (?, ?, ?, ?, ?, ?)", schedules)
    conn.executemany("INSERT INTO meeting VALUES (?, ?, ?, ?, ?, ?)", meetings)
    conn.commit()

    n_cases = conn.execute("SELECT COUNT(*) FROM legal_case").fetchone()[0]
    n_mine = conn.execute("SELECT COUNT(DISTINCT case_id) FROM case_member WHERE emp_id = 'E001'").fetchone()[0]
    conn.close()
    print(f"생성 완료: {path} · 사건 {n_cases}건 · 데모 사용자(E001) 관련 사건 {n_mine}건")
    return path


if __name__ == "__main__":
    main()
