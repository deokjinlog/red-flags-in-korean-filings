"""연속값 신호 검정 — 드문 사건 대신 **모든 회사가 값을 갖는 특징**으로.

왜 바꾸나:
  순환출자·상호보유는 보유율이 각각 1.7%·3.9% 라, 부실(연 1%)과의 교집합이
  0.017% 수준이다. 양성 20건을 모으려면 10만 기업-연도가 필요한데 우리는 연 9천이다.
  **데이터를 더 모아도 안 되는 구조**다.

  연속값은 다르다. 차수·매개중심성·도달범위는 모든 회사가 값을 가지므로, 상위 N%
  대 나머지로 가르면 양쪽 군이 다 크다. 표본 부족이 사라진다.

무엇을 지키나 (앞과 동일):
  특징은 T 이전 · 라벨은 T 이후 · 회사당 1관측 · 못 정하면 못 정했다고 한다.

사용:
    uv run python scripts/run_continuous_test.py --as-of 20220630,20230630 --top-pct 25
"""
from __future__ import annotations

import argparse
from collections import defaultdict, deque

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from dartweave.db.asof import events_after, latest_edges_at
from dartweave.signal.test import permutation_test
from dartweave.structure.cluster import cluster
from dartweave.structure.project import project


def continuous_features(edges) -> dict[str, dict[str, float]]:
    """회사별 연속 특징. 전부 그래프 구조만으로 나온다."""
    g = project(edges, undirected=True)
    g.simplify()
    codes = list(g.vs["corp_code"])
    btw = g.betweenness()
    deg = g.degree()

    nat = project(edges, undirected=False)
    ncodes = list(nat.vs["corp_code"])
    outd = dict(zip(ncodes, nat.degree(mode="out")))
    ind = dict(zip(ncodes, nat.degree(mode="in")))

    und = defaultdict(set)
    for a, b, _ in edges:
        und[a].add(b)
        und[b].add(a)
    reach = {}
    for n in codes:
        dist, q = {n: 0}, deque([n])
        while q:
            cur = q.popleft()
            if dist[cur] >= 2:
                continue
            for nx in und.get(cur, ()):
                if nx not in dist:
                    dist[nx] = dist[cur] + 1
                    q.append(nx)
        reach[n] = len(dist) - 1

    r = cluster(g, objective="modularity", seed=1)
    size = defaultdict(int)
    for m in r.membership:
        size[m] += 1
    csize = {c: size[m] for c, m in zip(codes, r.membership)}

    return {
        "degree":      dict(zip(codes, deg)),
        "betweenness": dict(zip(codes, btw)),
        "out_degree":  {c: outd.get(c, 0) for c in codes},
        "in_degree":   {c: ind.get(c, 0) for c in codes},
        "reach_2hop":  reach,
        "cluster_size": csize,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--db", default="sqlite:///data/timeseries.db")
    p.add_argument("--as-of", required=True)
    p.add_argument("--within-days", type=int, default=730)
    p.add_argument("--top-pct", type=float, default=25.0,
                   help="상위 몇 %% 를 신호군으로 볼 것인가")
    p.add_argument("--runs", type=int, default=3000)
    args = p.parse_args(argv)

    points = [t.strip() for t in args.as_of.split(",") if t.strip()]
    # 회사당 1관측: 특징은 **첫 등장 시점** 값, 라벨은 어느 시점에든 부실이면 True
    first_feat: dict[str, dict[str, float]] = {}
    distressed: set[str] = set()
    universe: set[str] = set()

    for t in points:
        with Session(create_engine(args.db)) as s:
            latest = latest_edges_at(s, t)
            events = events_after(s, t, within_days=args.within_days)
        edges = [(f.source_corp_code, f.target_corp_code, f.rel_type)
                 for f in latest.values()]
        if not edges:
            continue
        feats = continuous_features(edges)
        codes = set(feats["degree"])
        universe |= codes
        distressed |= {e.corp_code for e in events} & codes
        for c in codes:
            first_feat.setdefault(c, {k: v[c] for k, v in feats.items() if c in v})
        print(f"  {t}: 대상 {len(codes):,}사 · 창 안 부실 "
              f"{len({e.corp_code for e in events} & codes):,}사")

    print(f"\n회사 {len(universe):,} · 부실 {len(distressed):,} · 상위 {args.top_pct:g}% 기준\n")

    for name in ("degree", "betweenness", "out_degree", "in_degree",
                 "reach_2hop", "cluster_size"):
        vals = [(c, f.get(name, 0)) for c, f in first_feat.items() if name in f]
        if not vals:
            continue
        vals.sort(key=lambda x: -x[1])
        k = max(1, int(len(vals) * args.top_pct / 100))
        top = [c in distressed for c, _ in vals[:k]]
        rest = [c in distressed for c, _ in vals[k:]]
        cut = vals[k - 1][1]
        r = permutation_test(top, rest, runs=args.runs)
        print(f"  {name:13s} 상위값≥{cut:>10.1f}  {r.verdict.value:15s} {r.explain()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
