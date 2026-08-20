"""고립 신호가 교란을 통제하고도 남는가 — 통제 설정을 흔들어가며 본다.

무엇을 검사하나:
  "대기업집단에서 고립된 회사가 감사의견 문제가 많다" 는 통제 전 ×2.61 이다.
  그런데 고립군은 **작은 회사**에 몰려 있고, **특정 업종**에 몰려 있다. 둘 다
  원래 문제가 많은 쪽이다. 규모와 업종을 맞춰놓고도 차이가 남아야 신호다.

교란 두 개:
  규모  자산총계. 공시 건수는 쓰면 안 된다 — 부실한 회사가 공시를 많이 낸다
        (유상증자·소송·관리종목). 층화 변수가 결과변수와 얽히면 통제가 왜곡이 된다.
  업종  표준산업분류(DART 기업개황). 실측 고립률 41~88% · 문제율 0~11.8% 이고
        둘이 같은 방향으로 움직인다 — 금융은 고립도 문제도 적고, 의료정밀은 둘 다 많다.

왜 한 설정만 보면 안 되나:
  층을 몇 개로 나누고 업종을 몇 자리로 자르냐는 **우리가 고른 값**이다. 층1에서
  군집 해상도를 0.5~2.0 으로 흔들었더니 답이 1.85배 변해서 결론을 반려했다.
  같은 규율을 여기에도 적용한다 — 설정을 흔들어보고, **가장 보수적인 설정의 답**을
  결론으로 삼는다. 유의해지는 설정을 골라 쓰는 건 파라미터 고르기다.

사용:
    uv run python scripts/test_isolation_controlled.py
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from dartweave.screen.audit import has_going_concern, normalize_opinion
from dartweave.signal.test import (
    Verdict,
    mantel_haenszel_ratio,
    stratified_permutation_test,
)

# 흔들어볼 통제 설정 — (자산 층 수, 업종 코드 자릿수). 0 자리는 업종 통제 없음.
GRID = [(1, 0), (4, 0), (2, 1), (2, 2), (3, 1), (3, 2), (4, 1), (4, 2)]


def neighbours_of(edges):
    nb = defaultdict(set)
    for a, b, *_ in edges:
        nb[a].add(b)
        nb[b].add(a)
    return nb


def split(codes, members, nb):
    """소속 / 미소속·연결 / 미소속·고립."""
    out = {"소속": [], "연결": [], "고립": []}
    for c in codes:
        if c in members:
            out["소속"].append(c)
        elif nb[c] & members:
            out["연결"].append(c)
        else:
            out["고립"].append(c)
    return out


def cells(pool, assets, industry, members, nb, label, n_strata, digits):
    """자산 층 × 업종 교차 셀. 셀이 작아도 버리지 않는다 — MH 는 희박한 표에 쓰라고 만든 것이다."""
    ordered = sorted(pool, key=lambda c: assets[c])
    size = max(1, len(ordered) // n_strata)
    buckets: dict[tuple, list[str]] = defaultdict(list)
    for i in range(n_strata):
        chunk = ordered[i * size:] if i == n_strata - 1 else ordered[i * size:(i + 1) * size]
        for c in chunk:
            buckets[(i, industry[c][:digits] if digits else "")].append(c)
    out = []
    for codes in buckets.values():
        g = split(codes, members, nb)
        out.append(([c in label for c in g["고립"]],
                    [c in label for c in g["소속"] + g["연결"]]))
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--graph", default="data/graph_listed.json")
    p.add_argument("--members", default="data/conglomerate_members.json")
    p.add_argument("--audit", default="data/audit_opinions.json")
    p.add_argument("--assets", default="data/assets.json")
    p.add_argument("--industry", default="data/industry.json")
    p.add_argument("--runs", type=int, default=20000)
    args = p.parse_args(argv)

    paths = (args.graph, args.members, args.audit, args.assets, args.industry)
    for path in paths:
        if not Path(path).exists():
            print(f"입력이 없습니다: {path}")
            return 2
    read = lambda f: json.loads(Path(f).read_text(encoding="utf-8"))  # noqa: E731

    edges = read(args.graph)["edges"]
    members = set(read(args.members)["members"])
    audit = read(args.audit)
    assets = {k: float(v) for k, v in read(args.assets).items() if v}
    industry = {k: str(v) for k, v in read(args.industry).items() if v}

    label = {c for c, rows in audit.items()
             if any(normalize_opinion(r["opinion"]).is_adverse for r in rows)
             or any(has_going_concern(r["emphasis"]) for r in rows)}

    # 커버리지 편향 — 그래프 밖 회사는 오히려 문제가 적다(2.2% vs 6.6%). 섞으면 흐려진다.
    in_graph = {v for e in edges for v in e[:2]}
    nb = neighbours_of(edges)
    pool = sorted(c for c in audit
                  if c in in_graph and c in assets and c in industry)
    g = split(pool, members, nb)

    print(f"\n대상 {len(pool):,}사 (그래프 안 · 자산·업종 확보) · "
          f"감사의견 문제 {len(label & set(pool)):,}사")
    print("\n[통제 전]")
    for k in ("소속", "연결", "고립"):
        hit = sum(1 for c in g[k] if c in label)
        print(f"  {k:4s} {hit / len(g[k]) * 100:5.1f}%  ({hit}/{len(g[k])})")

    print(f"\n[통제 설정을 흔든다 — 순열 {args.runs:,}회]")
    print(f"  {'자산층':>5s} {'업종':>6s} {'셀':>4s} {'배율':>6s} {'p':>8s}   판정")
    results = []
    for n_strata, digits in GRID:
        st = cells(pool, assets, industry, members, nb, label, n_strata, digits)
        r = stratified_permutation_test(st, runs=args.runs)
        mh = mantel_haenszel_ratio(st)
        if mh is None or r.p_value is None:
            continue
        results.append((n_strata, digits, mh, r.p_value, r.verdict))
        tag = "통제 없음" if (n_strata, digits) == (1, 0) else ""
        print(f"  {n_strata:5d} {digits or '-':>6} {len(st):4d} "
              f"×{mh:5.2f} {r.p_value:8.4f}   {r.verdict.value} {tag}")

    controlled = [r for r in results if (r[0], r[1]) != (1, 0)]
    if not controlled:
        return 0
    lo = min(r[2] for r in controlled)
    hi = max(r[2] for r in controlled)
    worst = max(controlled, key=lambda r: r[3])      # 가장 보수적 = p 가 가장 큰 설정
    supported = sum(1 for r in controlled if r[4] is Verdict.SUPPORTED)

    print(f"\n  배율 범위 ×{lo:.2f}~×{hi:.2f} (흔들림 {hi / lo:.2f}배) · "
          f"유의한 설정 {supported}/{len(controlled)}")
    print(f"  가장 보수적인 설정: 자산 {worst[0]}층 × 업종 {worst[1]}자리 "
          f"→ ×{worst[2]:.2f} · p={worst[3]:.4f}")
    if worst[4] is Verdict.SUPPORTED:
        print("\n→ 가장 보수적인 설정에서도 유의하다. 교란으로는 설명되지 않는다.")
    else:
        print("\n→ **채택하지 않는다.** 방향은 모든 설정에서 일관되지만, 통제를 촘촘히 할수록"
              "\n   배율이 계속 줄고 유의성이 사라진다. 유의해지는 설정을 골라 쓰면 그건"
              "\n   파라미터 고르기다 — 층1에서 모듈러리티를 반려한 것과 같은 이유다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
