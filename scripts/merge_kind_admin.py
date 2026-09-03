"""KIND 관리종목 지정 이력을 라벨 테이블에 넣는다 — **부실보다 한 단계 이른 사건**으로.

왜 따로 두나:
  기존 부실 라벨(부도·회생·관리절차·상장폐지)은 **되돌릴 수 없는** 사건이다. 관리종목
  지정은 다르다 — 해제가 실제로 311건 있다. 둘을 한 덩어리로 섞으면 "부실" 이라는
  말이 조용히 바뀌고, 지금까지 잰 모든 배율이 다른 뜻이 된다.

  그래서 `관리종목(부실 사유)` 라는 별도 종류로 넣고, `labels.py` 의 WARNING_TYPES 로
  묶는다. 검정은 두 벌로 돌려 **둘 다 보고**한다. 하나만 쓰면 그게 유리해서 골랐는지
  알 수 없다.

거르는 것 둘:

  1. **규모·유동성 사유는 부실이 아니다.** 시가총액·주가·거래량 미달은 "작다" 는
     뜻이고, 우리가 7설정으로 통제하는 그 규모와 정면으로 충돌한다. 스팩·지배구조도 뺀다.

  2. **인수로 인한 기계적 지정을 뺀다.** 공개매수로 지분이 몰리면 주식분산요건이
     깨져 "상장폐지사유 발생" 으로 관리종목에 지정되는데, 그건 부실이 아니라 비상장화다.
     실측으로 시차가 딱 갈린다 — 인수 5건(루트로닉·에코마케팅·제이시스메디칼·코엔텍·
     커넥트웨이브)이 전부 지정 후 **14~18일**에 합병 폐지됐고, 그 다음이 543일
     (오스템임플란트, 2022 횡령은 진짜 부실이고 2023 자진폐지는 무관)이다.
     90일을 임계로 두면 둘 사이가 넓어 어디로 잡아도 같은 답이 나온다.

사용:
    uv run python scripts/merge_kind_admin.py            # 미리보기
    uv run python scripts/merge_kind_admin.py --load
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
from collections import Counter
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from dartweave.db.models import Base, DistressEvent
from dartweave.signal.labels import is_distress

EVENT_TYPE = "관리종목(부실 사유)"
TAKEOVER_DAYS = 90


def _date(s: str) -> dt.date:
    return dt.date(int(s[:4]), int(s[4:6]), int(s[6:8]))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--db", default="sqlite:///data/timeseries.db")
    p.add_argument("--src", default="data/kind_admin_history.csv")
    p.add_argument("--corpcode", default="data/corpcode.json")
    p.add_argument("--delisting", default="data/delisting.json")
    p.add_argument("--reasons", default="data/kind_admin_reasons.csv",
                   help="제목에 사유가 없는 건을 본문에서 채운 것")
    p.add_argument("--load", action="store_true")
    args = p.parse_args(argv)

    rows = list(csv.DictReader(Path(args.src).open(encoding="utf-8")))
    cc = json.loads(Path(args.corpcode).read_text(encoding="utf-8"))
    dl = [x for x in json.loads(Path(args.delisting).read_text(encoding="utf-8"))
          if x.get("corp_code")]
    # 회사별 '부실 아님' 폐지일. 인수 판별에 쓴다.
    benign: dict[str, list[dt.date]] = {}
    for x in dl:
        if not is_distress(x["kind"]):
            benign.setdefault(x["corp_code"], []).append(_date(x["date"]))

    # 제목에 사유가 없던 건은 본문에서 채운 값으로 덮는다. 이걸 안 하면 유가증권
    # 회사만 라벨에서 빠진다 — 실측으로 사유불명 107건이 **전부 유가증권시장본부**였다.
    # 결측이 아니라 시장 단위 편향이고, 그건 신호가 아니라 수집 방식이 만든 것이다.
    filled: dict[str, dict] = {}
    rpath = Path(args.reasons)
    if rpath.exists():
        for row in csv.DictReader(rpath.open(encoding="utf-8")):
            filled[row["acptno"]] = row

    kept: dict[tuple[str, str], dict] = {}
    drop = Counter()
    for r in rows:
        got = filled.get(r.get("acptno", ""))
        if got and r["reason"] in ("사유불명", "기타사유"):
            r = {**r, "reason": got["reason"], "is_distress": got["is_distress"]}
        if r["event"] != "지정":
            drop[f"사건 아님({r['event']})"] += 1
            continue
        if r["is_distress"] != "1":
            drop[f"부실 사유 아님({r['reason']})"] += 1
            continue
        code = cc.get(r["corp_name"])
        if not code:
            drop["corp_code 미해소"] += 1
            continue
        when = _date(r["date"])
        if any(0 <= (d - when).days <= TAKEOVER_DAYS for d in benign.get(code, [])):
            drop["인수로 인한 기계적 지정"] += 1
            continue
        kept.setdefault((code, r["date"]), r)

    engine = create_engine(args.db)
    Base.metadata.create_all(engine)
    added = skipped = 0
    with Session(engine) as s:
        have = set(s.scalars(select(DistressEvent.rcept_no)))
        for (code, when), r in sorted(kept.items()):
            key = f"ADMIN{when}{code}"
            if key in have:
                skipped += 1
                continue
            if args.load:
                s.add(DistressEvent(rcept_no=key, corp_code=code,
                                    event_type=EVENT_TYPE, rcept_dt=when,
                                    detail={"title": r["title"], "reason": r["reason"],
                                            "name": r["corp_name"]}))
            have.add(key)
            added += 1
        if args.load:
            s.commit()

    print(f"원본 {len(rows):,}건 → 라벨 후보 {len(kept):,}건 "
          f"(회사 {len({c for c, _ in kept}):,}사)")
    for k, n in drop.most_common(8):
        print(f"   제외 {k:<28}{n:>5}건")
    print(f"\n{'적재' if args.load else '적재 예정'} {added:,}건 · 이미 있음 {skipped:,}건")
    by_reason = Counter(r["reason"] for r in kept.values())
    print("   사유:", dict(by_reason.most_common()))
    if not args.load:
        print("\n실제로 넣으려면 --load 를 붙이세요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
