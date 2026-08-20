"""고립 신호를 **앞을 보는 설계**로 검정한다 — 감사의견 대신 실제 부실 사건.

왜 라벨을 바꾸나:
  감사의견은 **이미 드러난 문제**다. "사도 되나" 는 드러나기 전을 묻는 질문이라,
  기준시점 T 의 구조로 T 이후의 부실을 맞히는지 봐야 한다.

시점 분리:
  엣지    T 시점에 이미 공시된 것만 (`db/asof.py` 가 as_of·rcept_dt 둘 다 건다)
  라벨    T 이후 730일 안의 부도·회생·관리절차·영업정지 (해산은 부실이 아니라 제외)
  자산    T 이전 사업연도 값 — 2022년 6월에 서서 2023년 자산으로 층을 나누면
          미래를 보는 것이다. `assets_by_year.json` 이 연도별로 들고 있다.
  업종    현재 값을 쓴다. 업종은 거의 안 바뀌지만 엄밀히는 시점 분리가 아니다.

T 를 여러 개 돌리되 **합치지 않는다.** 같은 회사를 두 번 세면 p 가 부풀려진다 —
순환출자 검정에서 ×4.18 p=0.0005 가 그렇게 만들어졌다.

사용:
    uv run python scripts/test_isolation_forward.py
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from dartweave.db.asof import events_after, latest_edges_at
from dartweave.signal.test import (
    Verdict,
    mantel_haenszel_ratio,
    stratified_permutation_test,
)
from test_isolation_controlled import GRID, cells, neighbours_of, split


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--db", default="sqlite:///data/timeseries.db")
    p.add_argument("--as-of", default="20220630,20230630")
    p.add_argument("--within-days", type=int, default=730)
    p.add_argument("--members", default="data/conglomerate_members.json")
    p.add_argument("--assets", default="data/assets_by_year.json")
    p.add_argument("--industry", default="data/industry.json")
    p.add_argument("--runs", type=int, default=20000)
    args = p.parse_args(argv)

    read = lambda f: json.loads(Path(f).read_text(encoding="utf-8"))  # noqa: E731
    members = set(read(args.members)["members"])
    by_year = {y: {k: float(v) for k, v in d.items()} for y, d in read(args.assets).items()}
    industry = {k: str(v) for k, v in read(args.industry).items() if v}
    engine = create_engine(args.db)

    for T in [x.strip() for x in args.as_of.split(",") if x.strip()]:
        assets_year = str(int(T[:4]) - 1)      # T 시점에 이미 공시된 마지막 사업연도
        assets = by_year.get(assets_year, {})
        with Session(engine) as s:
            latest = latest_edges_at(s, T)
            events = events_after(s, T, within_days=args.within_days)
        edges = [(f.source_corp_code, f.target_corp_code, f.rel_type)
                 for f in latest.values()]
        nb = neighbours_of(edges)
        label = {e.corp_code for e in events if "해산" not in e.event_type}
        pool = sorted(c for c in nb if c in assets and c in industry)
        g = split(pool, members, nb)

        print(f"\n{'=' * 68}\nT={T} · 엣지 {len(edges):,} · 대상 {len(pool):,}사 "
              f"({assets_year}년 자산 기준) · 이후 {args.within_days}일 부실 "
              f"{len(label & set(pool))}사")
        for k in ("소속", "연결", "고립"):
            hit = sum(1 for c in g[k] if c in label)
            n = len(g[k])
            print(f"  {k:4s} {hit / n * 100 if n else 0:5.2f}%  ({hit}/{n})")

        print(f"\n  {'자산층':>5s} {'업종':>6s} {'셀':>4s} {'배율':>6s} {'p':>8s}   판정")
        results = []
        for n_strata, digits in GRID:
            st = cells(pool, assets, industry, members, nb, label, n_strata, digits)
            r = stratified_permutation_test(st, runs=args.runs)
            mh = mantel_haenszel_ratio(st)
            if r.verdict is Verdict.TOO_FEW:
                print(f"  {n_strata:5d} {digits or '-':>6} {len(st):4d} "
                      f"{'—':>6} {'—':>8}   {r.explain()}")
                break
            results.append((mh, r.p_value, r.verdict))
            print(f"  {n_strata:5d} {digits or '-':>6} {len(st):4d} "
                  f"×{mh:5.2f} {r.p_value:8.4f}   {r.verdict.value}"
                  f"{'   ← 통제 없음' if (n_strata, digits) == (1, 0) else ''}")

        controlled = results[1:]
        if not controlled:
            continue
        worst = max(controlled, key=lambda x: x[1])
        sup = sum(1 for x in controlled if x[2] is Verdict.SUPPORTED)
        print(f"\n  가장 보수적인 설정 → ×{worst[0]:.2f} · p={worst[1]:.4f} "
              f"· 유의한 설정 {sup}/{len(controlled)}")
        print("  → 채택" if worst[2] is Verdict.SUPPORTED else "  → 채택하지 않음")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
