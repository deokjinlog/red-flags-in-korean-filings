"""신호 검정 실행 — "이 신호를 가진 기업은 이후 부실이 유의하게 많은가".

설계상 지키는 것 셋:
  1. **특징은 T 이전, 라벨은 T 이후.** `db/asof.py` 가 강제한다. 이 경계가 흐려지면
     미래를 보고 예측한 셈이라 결과가 통째로 무의미하다.
  2. **유의성은 대조로 본다.** "신호군 부실률 12%" 는 그 자체로 뜻이 없다.
     비신호군이 몇 %인지가 있어야 판단이 된다.
  3. **못 정하면 못 정했다고 한다.** 신호군 부실이 20건 미만이면 `TOO_FEW`.

지금 검정하는 신호(그래프에서 계산 가능한 것):
  circular   순환출자 고리를 가졌는가
  mutual     상호 지분 보유가 있는가
  choke      2홉 안에 공동의존점이 있는가

사용:
    uv run python scripts/run_signal_test.py --as-of 20250601 --within-days 365
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict, deque
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from dartweave.db.asof import assert_no_look_ahead, events_after, latest_edges_at
from dartweave.signal.test import permutation_test
from dartweave.structure.project import project

SIGNALS = ("circular", "mutual", "choke")


def build_features(edges, chokepoints, hops=2):
    """기업별 신호 보유 여부. 세 신호 모두 **그래프 구조만으로** 계산된다."""
    out_adj, und = defaultdict(set), defaultdict(set)
    for a, b, _ in edges:
        out_adj[a].add(b)
        und[a].add(b)
        und[b].add(a)
    nodes = sorted(und)

    feats = {s: set() for s in SIGNALS}
    for n in nodes:
        # 상호 보유 — 내가 가진 상대가 나도 가졌나
        if any(n in out_adj.get(t, ()) for t in out_adj.get(n, ())):
            feats["mutual"].add(n)
        # 순환출자 — 길이 3 이상 고리 (상호 보유는 따로 센다)
        q, found = deque([[n]]), False
        explored = 0
        while q and not found and explored < 4000:
            explored += 1
            path = q.popleft()
            if len(path) > 5:
                continue
            for nx in out_adj.get(path[-1], ()):
                if nx == n and len(path) >= 3:
                    found = True
                    break
                if nx not in path:
                    q.append([*path, nx])
        if found:
            feats["circular"].add(n)
        # 공동의존점 근접
        dist, dq = {n: 0}, deque([n])
        while dq:
            cur = dq.popleft()
            if dist[cur] >= hops:
                continue
            for nx in und.get(cur, ()):
                if nx not in dist:
                    dist[nx] = dist[cur] + 1
                    dq.append(nx)
        if any(c in dist and c != n for c in chokepoints):
            feats["choke"].add(n)
    return nodes, feats


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--db", default="sqlite:///data/timeseries.db")
    p.add_argument("--as-of", required=True, help="특징 계산 시점 (YYYYMMDD)")
    p.add_argument("--within-days", type=int, default=365, help="라벨 관찰 창")
    p.add_argument("--runs", type=int, default=2000)
    args = p.parse_args(argv)

    with Session(create_engine(args.db)) as s:
        latest = latest_edges_at(s, args.as_of)
        events = events_after(s, args.as_of, within_days=args.within_days)

    edges = [(f.source_corp_code, f.target_corp_code, f.rel_type) for f in latest.values()]
    if not edges:
        print(f"{args.as_of} 시점에 알 수 있었던 관계가 없습니다. "
              "수집이 더 필요하거나 시점이 이릅니다.")
        return 3

    g = project(edges, undirected=True); g.simplify()
    ranked = sorted(zip(g.vs["corp_code"], g.betweenness()), key=lambda x: -x[1])
    chokes = {c for c, _ in ranked[:12]}

    nodes, feats = build_features(edges, chokes)
    distressed = {e.corp_code for e in events}
    assert_no_look_ahead(args.as_of, min(e.rcept_dt for e in events) if events else "99991231")

    print(f"\n특징 시점 {args.as_of} · 라벨 창 +{args.within_days}일")
    print(f"대상 {len(nodes):,}개사 · 관계 {len(edges):,} · "
          f"창 안 부실 사건 {len(events):,}건 (그중 대상 내 {len(distressed & set(nodes)):,}사)\n")

    for sig in SIGNALS:
        have = [n in distressed for n in nodes if n in feats[sig]]
        not_have = [n in distressed for n in nodes if n not in feats[sig]]
        if not have or not not_have:
            print(f"  {sig:10s} 한쪽 군이 비어 검정 불가")
            continue
        r = permutation_test(have, not_have, runs=args.runs)
        print(f"  {sig:10s} {r.verdict.value:16s} {r.explain()}")

    Path("data/last_signal_test.json").write_text(json.dumps({
        "as_of": args.as_of, "within_days": args.within_days,
        "nodes": len(nodes), "events": len(events)}, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
