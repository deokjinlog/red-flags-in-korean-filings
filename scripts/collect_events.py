"""부실 사건 라벨 수집 — 신호 검정의 정답지.

주요사항보고서(pblntf_ty=B)에서 부실 유형만 골라 `distress_event` 에 넣는다.
corp_code 없이 기간으로 훑으면 **전 기업**이 대상이라, 그래프에 없는 회사도 잡힌다.

실측(2024 1분기 표본 1,200건): 영업정지 6 · 관리절차 6 · 해산 2 · 회생절차 1 · 부도 1.
연간 추정 96건이고 그중 부도급이 50건 수준 — 예측 모델에는 부족하고 신호 검정에는 쓴다.

⚠️ corp_code 없는 검색은 **3개월 제한**이 있어 분기로 끊는다.

사용:
    uv run python scripts/collect_events.py --years 2023,2024
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from dartweave.config import Settings
from dartweave.dart.client import DartClient
from dartweave.dart.status import Action, classify
from dartweave.db.models import Base, DistressEvent

DB = "sqlite:///data/timeseries.db"
# 부실 유형. 보고서명에 그대로 들어 있어 본문을 안 읽어도 분류된다.
KINDS = {
    "부도발생": "부도", "회생절차": "회생", "관리절차": "관리절차",
    "파산": "파산", "영업정지": "영업정지",
    # ⚠️ '해산' 은 **부실이 아니다.** 실측에서 52건을 뽑았더니 은평피에프브이·
    # 제4차모빌리티홀딩스처럼 PFV·SPC 의 만기 해산이 대부분이었다 — 예정된 종료다.
    # 라벨에 넣으면 정답지가 오염돼 검정이 무의미해진다. 별도 유형으로만 남긴다.
    "해산사유": "해산(부실아님)",
}
# 신호 검정에 쓸 수 있는 유형. 해산은 뺀다.
DISTRESS_KINDS = {"부도", "회생", "관리절차", "파산", "영업정지"}
QUARTERS = [("0101", "0331"), ("0401", "0630"), ("0701", "0930"), ("1001", "1231")]


def classify_event(report_nm: str) -> str | None:
    for key, label in KINDS.items():
        if key in report_nm:
            return label
    return None


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--years", default="2024")
    p.add_argument("--db", default=DB)
    p.add_argument("--max-pages", type=int, default=25)
    args = p.parse_args(argv)

    s = Settings.from_env()
    if not s.dart_api_key:
        print("DART_API_KEY 가 없습니다.", file=sys.stderr)
        return 2

    Path("data").mkdir(exist_ok=True)
    engine = create_engine(args.db)
    Base.metadata.create_all(engine)
    client = DartClient(api_key=s.dart_api_key)
    added = seen = 0
    try:
        with Session(engine) as sess:
            for year in [y.strip() for y in args.years.split(",") if y.strip()]:
                for bgn, end in QUARTERS:
                    page = 1
                    while page <= args.max_pages:
                        r = client.get_json("list.json", {
                            "bgn_de": f"{year}{bgn}", "end_de": f"{year}{end}",
                            "pblntf_ty": "B", "page_no": str(page),
                            "page_count": "100"})
                        if classify(str(r.get("status", ""))) is not Action.OK:
                            break
                        for it in (r.get("list") or []):
                            seen += 1
                            nm = re.sub(r"\[.*?\]", "", it.get("report_nm", "")).strip()
                            kind = classify_event(nm)
                            if not kind:
                                continue
                            rno = it.get("rcept_no", "")
                            if sess.get(DistressEvent, rno):
                                continue
                            sess.add(DistressEvent(
                                rcept_no=rno, corp_code=it.get("corp_code", ""),
                                event_type=kind, rcept_dt=re.sub(r"\D", "", str(it.get("rcept_dt", ""))),
                                detail={"corp_name": it.get("corp_name"), "report_nm": nm}))
                            added += 1
                        if page >= int(r.get("total_page", 1)):
                            break
                        page += 1
                    sess.commit()
                    print(f"  {year}{bgn[:2]}분기 누적 {added}건 (훑은 공시 {seen:,})")
    finally:
        client.close()

    with Session(engine) as sess:
        rows = sess.execute(
            select(DistressEvent.event_type).order_by(DistressEvent.event_type)
        ).scalars().all()
    from collections import Counter
    c = Counter(rows)
    usable = sum(n for k, n in c.items() if k in DISTRESS_KINDS)
    print(f"\n수집 {len(rows):,}건 / 훑은 주요사항보고 {seen:,}건")
    for k, n in c.most_common():
        mark = "" if k in DISTRESS_KINDS else "   ← 검정에서 제외"
        print(f"   {k:14s} {n:>4}건{mark}")
    print(f"\n검정에 쓸 수 있는 부실 라벨 {usable:,}건")
    print(f"→ {args.db}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
