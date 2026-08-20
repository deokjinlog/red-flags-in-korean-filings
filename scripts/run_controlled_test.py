"""탐지 편향 통제 — 공시 건수를 맞춰놓고도 신호가 남는가.

문제:
  "지분 관계가 많은 회사가 부실 2배" 가 나왔는데, 관계가 많은 회사는 공시를 많이 하는
  회사이기도 하다. 부실 공시가 잡힐 확률 자체가 높아서 그렇게 보일 수 있다.

방법 — 층화(stratification):
  회사를 총 공시 건수로 층을 나누고, **같은 층 안에서만** 신호군 대 대조군을 비교한다.
  층 안에서는 공시 건수가 비슷하니 탐지 확률도 비슷하다. 그러고도 차이가 남으면
  공시량으로는 설명 안 되는 것이다.

  층별 결과를 합칠 때 단순 합산하면 층 크기가 큰 쪽이 지배한다. 그래서 층마다 따로
  내고, 방향이 일관되는지를 본다 — 층 대부분에서 같은 방향이면 견고한 것이다.

사용:
    uv run python scripts/run_controlled_test.py --as-of 20220630,20230630 --feature degree
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from dartweave.db.asof import events_after, latest_edges_at
from dartweave.signal.test import permutation_test
from run_continuous_test import continuous_features

N_STRATA = 4


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--db", default="sqlite:///data/timeseries.db")
    p.add_argument("--as-of", required=True)
    p.add_argument("--within-days", type=int, default=730)
    p.add_argument("--feature", default="degree")
    p.add_argument("--top-pct", type=float, default=25.0)
    p.add_argument("--runs", type=int, default=3000)
    p.add_argument("--counts", default="data/filing_counts.json")
    args = p.parse_args(argv)

    counts_path = Path(args.counts)
    if not counts_path.exists():
        print("공시 건수가 없습니다. `scripts/collect_filing_counts.py` 를 먼저 돌리세요.")
        return 2
    counts: dict[str, int] = json.loads(counts_path.read_text(encoding="utf-8"))

    first: dict[str, float] = {}
    distressed: set[str] = set()
    universe: set[str] = set()
    for t in [x.strip() for x in args.as_of.split(",") if x.strip()]:
        with Session(create_engine(args.db)) as s:
            latest = latest_edges_at(s, t)
            events = events_after(s, t, within_days=args.within_days)
        edges = [(f.source_corp_code, f.target_corp_code, f.rel_type)
                 for f in latest.values()]
        if not edges:
            continue
        feats = continuous_features(edges)[args.feature]
        universe |= set(feats)
        distressed |= {e.corp_code for e in events} & set(feats)
        for c, v in feats.items():
            first.setdefault(c, v)

    pool = [c for c in universe if c in counts]
    print(f"\n특징 {args.feature} · 회사 {len(universe):,} "
          f"(공시 건수 확보 {len(pool):,}) · 부실 {len(distressed):,}\n")
    if not pool:
        print("공시 건수가 겹치는 회사가 없습니다 — 수집이 더 필요합니다.")
        return 3

    pool.sort(key=lambda c: counts[c])
    size = max(1, len(pool) // N_STRATA)
    same_dir = 0
    for i in range(N_STRATA):
        chunk = pool[i * size: (i + 1) * size] if i < N_STRATA - 1 else pool[i * size:]
        if len(chunk) < 50:
            continue
        chunk.sort(key=lambda c: -first.get(c, 0))
        k = max(1, int(len(chunk) * args.top_pct / 100))
        top = [c in distressed for c in chunk[:k]]
        rest = [c in distressed for c in chunk[k:]]
        r = permutation_test(top, rest, runs=args.runs)
        lo, hi = counts[chunk[0]], counts[chunk[-1]]
        lift = f"×{r.lift:.2f}" if r.lift else "—"
        if r.lift and r.lift > 1:
            same_dir += 1
        print(f"  층{i+1} 공시 {min(counts[c] for c in chunk):>3}~"
              f"{max(counts[c] for c in chunk):>4}건 · {len(chunk):>4}사 "
              f"| 신호군 {r.signal_rate:.1%} vs {r.control_rate:.1%} {lift:>7} "
              f"| {r.verdict.value}")
    print(f"\n같은 방향(신호군이 높음) 층 {same_dir}/{N_STRATA}")
    print("층 대부분에서 같은 방향이면 공시량으로는 설명 안 되는 것이다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
