"""수집한 상장폐지를 부실 라벨 테이블에 적재한다.

접수번호가 없는 사건이라 `DELIST{상장폐지일}{corp_code}` 로 합성 키를 만든다.
같은 회사가 같은 날 두 번 상장폐지될 수는 없으니 이 키로 멱등이 보장된다.

corp_code 를 못 붙인 건 넣지 않는다 — 이름만 있는 라벨은 어느 회사인지 모르는 라벨이다.
실측으로 부실 상장폐지 154건 중 29건(19%)이 여기서 빠진다. 오래전 폐지돼 corpCode 에
이름이 남지 않은 회사들이고, 비슷한 이름에 억지로 붙이는 건 하지 않는다 —
이 저장소는 이미 그런 별칭 하나를 반려한 적이 있다.

사용:
    uv run python scripts/load_delisting.py --load
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from dartweave.db.models import Base, DistressEvent
from dartweave.signal.labels import is_distress


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--db", default="sqlite:///data/timeseries.db")
    p.add_argument("--src", default="data/delisting.json")
    p.add_argument("--load", action="store_true", help="실제로 적재한다")
    args = p.parse_args(argv)

    rows = json.loads(Path(args.src).read_text(encoding="utf-8"))
    usable = [r for r in rows if r.get("corp_code")]
    engine = create_engine(args.db)
    Base.metadata.create_all(engine)

    inserted = skipped = 0
    with Session(engine) as s:
        have = set(s.scalars(select(DistressEvent.rcept_no)))
        for r in usable:
            key = f"DELIST{r['date']}{r['corp_code']}"
            if key in have:
                skipped += 1
                continue
            if args.load:
                s.add(DistressEvent(rcept_no=key, corp_code=r["corp_code"],
                                    event_type=r["kind"], rcept_dt=r["date"],
                                    detail={"reason": r["reason"], "name": r["name"]}))
            have.add(key)
            inserted += 1
        if args.load:
            s.commit()

    kinds = Counter(r["kind"] for r in usable)
    print(f"\n대상 {len(rows):,}건 · corp_code 확보 {len(usable):,}건 "
          f"(미해소 {len(rows) - len(usable):,}건은 넣지 않음)")
    print(f"{'적재' if args.load else '적재 예정'} {inserted:,}건 · 이미 있음 {skipped:,}건")
    print(f"  그중 부실로 세는 것 "
          f"{sum(n for k, n in kinds.items() if is_distress(k)):,}건")
    if not args.load:
        print("\n실제로 넣으려면 --load 를 붙이세요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
