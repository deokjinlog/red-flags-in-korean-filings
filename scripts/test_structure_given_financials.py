"""재무를 알고 나서도 구조가 뭔가 보태는가.

왜 이 질문이 마지막인가:
  구조 신호는 단독으로 전부 떨어졌고, 재무는 결손금 하나가 통과했다. 그런데
  "단독으로 못 한다" 와 "아무것도 못 한다" 는 다른 말이다. 재무가 이미 말해주는
  걸 구조가 중복해서 말하는 것뿐일 수도 있고, 재무가 놓치는 걸 구조가 잡을 수도 있다.

  **결손금 여부를 층에 넣고** 구조를 검정하면 답이 나온다. 결손 기업끼리, 흑자
  기업끼리만 비교하니 재무로 설명되는 부분은 층 안에서 상쇄된다. 그러고도 차이가
  남으면 구조가 재무 위에 뭔가 얹는 것이다.

층에 들어가는 것:
  자산총계 층 × 업종 × 결손금 여부. 앞의 둘은 이미 쓰던 교란이고 마지막이 새로 추가된다.

사용:
    uv run python scripts/test_structure_given_financials.py
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from dartweave.db.asof import events_after, latest_edges_at
from dartweave.signal.test import (
    Verdict,
    mantel_haenszel_ratio,
    stratified_permutation_test,
)
from test_isolation_controlled import neighbours_of, split

# 자산 층 수 × 업종 자릿수. 결손금 여부는 항상 층에 들어간다.
GRID = [(2, 0), (2, 1), (3, 1), (2, 2), (3, 2)]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--db", default="sqlite:///data/timeseries.db")
    p.add_argument("--as-of", default="20220630,20230630")
    p.add_argument("--within-days", type=int, default=730)
    p.add_argument("--members", default="data/conglomerate_members.json")
    p.add_argument("--fin", default="data/fin_by_year.json")
    p.add_argument("--industry", default="data/industry.json")
    p.add_argument("--runs", type=int, default=8000)
    args = p.parse_args(argv)

    read = lambda f: json.loads(Path(f).read_text(encoding="utf-8"))  # noqa: E731
    members = set(read(args.members)["members"])
    fin = read(args.fin)
    industry = {k: str(v) for k, v in read(args.industry).items() if v}
    engine = create_engine(args.db)

    for T in [x.strip() for x in args.as_of.split(",") if x.strip()]:
        year = str(int(T[:4]) - 1)
        acc = fin.get(year, {})
        with Session(engine) as s:
            latest = latest_edges_at(s, T)
            events = events_after(s, T, within_days=args.within_days)
        edges = [(f.source_corp_code, f.target_corp_code, f.rel_type)
                 for f in latest.values()]
        nb = neighbours_of(edges)
        label = {e.corp_code for e in events if "해산" not in e.event_type}
        pool = sorted(c for c in nb
                      if c in industry and acc.get(c, {}).get("자산총계")
                      and "이익잉여금" in acc.get(c, {}))
        assets = {c: float(acc[c]["자산총계"]) for c in pool}
        deficit = {c for c in pool if float(acc[c]["이익잉여금"]) < 0}
        g = split(pool, members, nb)
        iso = set(g["고립"])

        print(f"\n{'=' * 72}\nT={T} · {year}년 재무 · 대상 {len(pool):,}사 "
              f"· 결손 {len(deficit):,}사 · 이후 부실 {len(label & set(pool))}사\n")
        print(f"  {'':10s} {'결손':>16s} {'흑자':>16s}")
        for tag, group in (("고립", iso), ("나머지", set(pool) - iso)):
            row = []
            for cond in (deficit, set(pool) - deficit):
                sub = group & cond
                hit = len(sub & label)
                row.append(f"{hit / len(sub) * 100 if sub else 0:5.2f}% ({hit}/{len(sub)})")
            print(f"  {tag:10s} {row[0]:>16s} {row[1]:>16s}")

        print(f"\n  {'자산층':>5s} {'업종':>5s} {'셀':>4s} {'배율':>6s} {'p':>8s}   판정")
        for n_strata, digits in GRID:
            ordered = sorted(pool, key=lambda c: assets[c])
            size = max(1, len(ordered) // n_strata)
            buckets: dict[tuple, list[str]] = defaultdict(list)
            for i in range(n_strata):
                chunk = (ordered[i * size:] if i == n_strata - 1
                         else ordered[i * size:(i + 1) * size])
                for c in chunk:
                    buckets[(i, industry[c][:digits] if digits else "",
                             c in deficit)].append(c)
            st = [([c in label for c in codes if c in iso],
                   [c in label for c in codes if c not in iso])
                  for codes in buckets.values()]
            r = stratified_permutation_test(st, runs=args.runs)
            if r.verdict is Verdict.TOO_FEW:
                print(f"  {n_strata:5d} {digits or '-':>5} {len(st):4d} "
                      f"{'—':>6} {'—':>8}   {r.explain()}")
                break
            print(f"  {n_strata:5d} {digits or '-':>5} {len(st):4d} "
                  f"×{mantel_haenszel_ratio(st):5.2f} {r.p_value:8.4f}   {r.verdict.value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
