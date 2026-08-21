"""구조 신호가 시점마다 커지는 게 진짜인가, 그래프가 채워진 탓인가.

무엇이 이상한가:
  고립 신호의 배율이 기준시점 순서대로 ×0.46 → ×0.88 → ×1.66 → ×2.02 로 단조
  증가한다. 그런데 같은 순서로 그래프 엣지도 4,794 → 15,445 로 는다. 둘 중 하나다.

  (가) 시간이 흐르며 고립이 실제로 더 위험해졌다
  (나) 초기 시점의 '고립' 은 진짜 고립이 아니라 **미수집**이었다

  (나) 라면 초기 시점의 널 결과는 신호가 없어서가 아니라 노출변수를 잘못 재서다.
  노출변수의 오분류는 **널 쪽으로 편향**시킨다 — 없는 신호를 만들지는 않지만,
  있는 신호를 지운다.

어떻게 가르나 — 진단용 역행 검정:
  가장 잘 채워진 T=2024 그래프의 분류를 **모든 기준시점에 적용**하고, 라벨은 각
  시점 것을 그대로 쓴다. 노출변수만 잘 재는 것으로 바꾸는 것이다.

  · 초기 시점에서도 효과가 나오면 → (나) 측정 문제였다
  · 여전히 안 나오면 → (가) 쪽에 무게가 실린다

⚠️ 이건 **진단이지 주장이 아니다.** 2024년 그래프를 2021년 시점에 쓰는 건 명백한
   미래 훔쳐보기다. 이 결과로 신호를 채택하지 않는다 — 두 설명 중 어느 쪽인지만 본다.

사용:
    uv run python scripts/diagnose_structure_trend.py
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from dartweave.db.asof import CensoredWindowError, events_after, latest_edges_at
from dartweave.signal.test import (
    mantel_haenszel_ratio,
    stratified_permutation_test,
)

GRID = [(1, 0), (2, 1), (3, 1), (3, 2), (4, 2)]


def classify(latest, members):
    nb = defaultdict(set)
    for f in latest.values():
        nb[f.source_corp_code].add(f.target_corp_code)
        nb[f.target_corp_code].add(f.source_corp_code)
    return {c: ("소속" if c in members else ("연결" if nb[c] & members else "고립"))
            for c in nb}


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
        if r.p_value is None:
            return None
        rows.append((mantel_haenszel_ratio(st), r.p_value))
    return rows


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--db", default="sqlite:///data/timeseries.db")
    p.add_argument("--as-of", default="20210630,20220630,20230630,20240630")
    p.add_argument("--reference", default="20240630", help="분류를 가져올 기준시점")
    p.add_argument("--within-days", type=int, default=730)
    p.add_argument("--runs", type=int, default=8000)
    args = p.parse_args(argv)

    read = lambda f: json.loads(Path(f).read_text(encoding="utf-8"))  # noqa: E731
    members = set(read("data/conglomerate_members.json")["members"])
    by_year = {y: {k: float(v) for k, v in d.items()}
               for y, d in read("data/assets_by_year.json").items()}
    industry = {k: str(v) for k, v in read("data/industry.json").items() if v}
    engine = create_engine(args.db)

    with Session(engine) as s:
        ref = classify(latest_edges_at(s, args.reference), members)
    ref_iso = {c for c, v in ref.items() if v == "고립"}
    print(f"\n기준 분류: T={args.reference} 그래프 · 노드 {len(ref):,} · "
          f"고립 {len(ref_iso):,}")

    print(f"\n  {'기준시점':10s} {'대상':>6s} {'부실':>5s}  "
          f"{'당시 분류':>18s}  {'T=2024 분류(진단)':>20s}")
    for T in [x.strip() for x in args.as_of.split(",") if x.strip()]:
        try:
            with Session(engine) as s:
                latest = latest_edges_at(s, T)
                events = events_after(s, T, within_days=args.within_days)
        except CensoredWindowError as e:
            print(f"  {T} 건너뜀 — {e}")
            continue
        own = classify(latest, members)
        own_iso = {c for c, v in own.items() if v == "고립"}
        label = {e.corp_code for e in events if "해산" not in e.event_type}
        assets = by_year.get(str(int(T[:4]) - 1), {})
        base = sorted(c for c in own if c in assets and c in industry)

        out = []
        for iso in (own_iso, ref_iso):
            pool = [c for c in base if c in ref] if iso is ref_iso else base
            rows = sweep(pool, assets, industry, label, iso, args.runs)
            if not rows:
                out.append("판정 불가")
                continue
            worst = max(rows[1:], key=lambda x: x[1])
            out.append(f"×{worst[0]:.2f} p={worst[1]:.4f}")
        print(f"  {T:10s} {len(base):6,} {len(label & set(base)):5d}  "
              f"{out[0]:>18s}  {out[1]:>20s}")

    print(f"\n  세 집단이 각각 어떻게 움직였나\n"
          f"  {'기준시점':10s} {'소속':>15s} {'연결':>15s} {'고립':>15s}")
    for T in [x.strip() for x in args.as_of.split(",") if x.strip()]:
        try:
            with Session(engine) as s:
                latest = latest_edges_at(s, T)
                events = events_after(s, T, within_days=args.within_days)
        except CensoredWindowError:
            continue
        own = classify(latest, members)
        label = {e.corp_code for e in events if "해산" not in e.event_type}
        assets = by_year.get(str(int(T[:4]) - 1), {})
        groups = defaultdict(list)
        for c, tag in own.items():
            if c in assets and c in industry:
                groups[tag].append(c)
        cells = []
        for tag in ("소속", "연결", "고립"):
            n = len(groups[tag])
            hit = sum(1 for c in groups[tag] if c in label)
            cells.append(f"{hit / n * 100 if n else 0:5.2f}% ({hit}/{n})")
        print(f"  {T:10s} {cells[0]:>15s} {cells[1]:>15s} {cells[2]:>15s}")
    print("\n  고립군은 단조로 오르고, 소속군은 초기 시점만 높다. 그 초기 값은 293사에"
          "\n  11건이라 흔들리는 자리다 — 역전의 상당 부분이 거기서 나온다.")

    print("\n  왼쪽은 시점 분리를 지킨 정식 결과, 오른쪽은 노출변수만 잘 재본 진단이다."
          "\n  오른쪽이 초기 시점에서도 커지면 초기의 널은 측정 탓이고,"
          "\n  왼쪽처럼 여전히 작으면 시간에 따른 실제 변화 쪽에 무게가 실린다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
