"""고립 신호가 최근에 나타난 게 특정 업종 때문인가.

무엇이 이상한가:
  고립 배율이 ×0.46 → ×0.88 → ×1.70 → ×2.34 로 최근 두 시점에서만 나타난다.
  그 시기가 부동산 PF 경색과 겹친다. 건설·부동산 회사들이 무더기로 부실해졌고
  그쪽에 미소속·고립이 많다면, "고립이 위험하다" 가 아니라 **"그때 건설이
  위험했다"** 를 고립이라는 이름으로 부른 것이 된다.

어떻게 가르나:
  · 부실 사건의 업종 구성이 시점마다 어떻게 변했는지 본다
  · 건설·부동산을 **빼고** 같은 검정을 돌린다. 빼도 남으면 업종 이야기가 아니다.
  · 건설·부동산 **안에서만** 돌려본다. 거기서만 나오면 업종 이야기가 맞다.

표준산업분류 중분류: 41 종합건설 · 42 전문직별공사 · 68 부동산업.

사용:
    uv run python scripts/diagnose_structure_sector.py
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from dartweave.db.asof import CensoredWindowError, events_after, latest_edges_at
from dartweave.signal.labels import is_distress
from dartweave.signal.test import (
    Verdict,
    mantel_haenszel_ratio,
    stratified_permutation_test,
)

CONSTRUCTION = {"41", "42", "68"}
GRID = [(1, 0), (2, 1), (3, 1), (3, 2)]


def isolated_set(latest, members):
    nb = defaultdict(set)
    for f in latest.values():
        nb[f.source_corp_code].add(f.target_corp_code)
        nb[f.target_corp_code].add(f.source_corp_code)
    return ({c for c in nb if c not in members and not (nb[c] & members)}, set(nb))


def sweep(pool, assets, industry, label, isolated, runs):
    rows = []
    for n_strata, digits in GRID:
        ordered = sorted(pool, key=lambda c: assets[c])
        size = max(1, len(ordered) // n_strata)
        buckets = defaultdict(list)
        for i in range(n_strata):
            chunk = (ordered[i * size:] if i == n_strata - 1
                     else ordered[i * size:(i + 1) * size])
            for c in chunk:
                buckets[(i, industry[c][:digits] if digits else "")].append(c)
        st = [([c in label for c in g if c in isolated],
               [c in label for c in g if c not in isolated])
              for g in buckets.values()]
        r = stratified_permutation_test(st, runs=runs)
        if r.verdict is Verdict.TOO_FEW:
            return None
        rows.append((mantel_haenszel_ratio(st), r.p_value))
    return rows


def line(rows):
    if not rows:
        return "판정 불가"
    worst = max(rows[1:], key=lambda x: x[1]) if len(rows) > 1 else rows[0]
    return f"×{worst[0]:.2f} p={worst[1]:.4f}"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--db", default="sqlite:///data/timeseries.db")
    p.add_argument("--as-of", default="20210630,20220630,20230630,20240630")
    p.add_argument("--within-days", type=int, default=730)
    p.add_argument("--runs", type=int, default=8000)
    args = p.parse_args(argv)

    read = lambda f: json.loads(Path(f).read_text(encoding="utf-8"))  # noqa: E731
    members = set(read("data/conglomerate_members.json")["members"])
    by_year = {y: {k: float(v) for k, v in d.items()}
               for y, d in read("data/assets_by_year.json").items()}
    industry = {k: str(v) for k, v in read("data/industry.json").items() if v}
    engine = create_engine(args.db)

    print(f"\n  {'기준시점':10s} {'부실':>4s} {'건설·부동산':>10s}  "
          f"{'전체':>16s} {'건설·부동산 제외':>18s} {'건설·부동산만':>16s}")
    for T in [x.strip() for x in args.as_of.split(",") if x.strip()]:
        try:
            with Session(engine) as s:
                latest = latest_edges_at(s, T)
                events = events_after(s, T, within_days=args.within_days)
        except CensoredWindowError as e:
            print(f"  {T} 건너뜀 — {e}")
            continue
        iso, nodes = isolated_set(latest, members)
        label = {e.corp_code for e in events if is_distress(e.event_type)}
        assets = by_year.get(str(int(T[:4]) - 1), {})
        pool = sorted(c for c in nodes if c in assets and c in industry)
        hit = label & set(pool)
        con = sum(1 for c in hit if industry[c][:2] in CONSTRUCTION)

        outs = []
        for subset in (pool,
                       [c for c in pool if industry[c][:2] not in CONSTRUCTION],
                       [c for c in pool if industry[c][:2] in CONSTRUCTION]):
            outs.append(line(sweep(subset, assets, industry, label, iso, args.runs)))
        print(f"  {T:10s} {len(hit):4d} {con:>9d}건  "
              f"{outs[0]:>16s} {outs[1]:>18s} {outs[2]:>16s}")

    print("\n  부실 사건의 업종 구성 (전체 라벨 기준)")
    with Session(engine) as s:
        allev = events_after(s, "20190101")
    per_year = defaultdict(Counter)
    for e in allev:
        if "해산" in e.event_type:
            continue
        tag = "건설·부동산" if industry.get(e.corp_code, "")[:2] in CONSTRUCTION else "그 외"
        per_year[e.rcept_dt[:4]][tag] += 1
    for y in sorted(per_year):
        c = per_year[y]
        tot = sum(c.values())
        print(f"    {y}  전체 {tot:4d}건 · 건설·부동산 {c['건설·부동산']:3d}건 "
              f"({c['건설·부동산'] / tot:.0%})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
