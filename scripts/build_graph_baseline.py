"""그래프 검사의 기준선 — 순환출자·상호보유·공동의존점이 얼마나 흔한가.

왜 필요한가:
  "순환출자 고리 3건 발견" 은 그 자체로 판단이 안 된다. 대기업 계열이면 흔한 건가?
  분포를 재야 "상위 몇 %" 라고 말할 수 있고, 그래야 임의 임계를 안 쓴다.

  공정위 공시 쪽은 이미 이렇게 바꿨다(`build_baseline.py`). 이건 그래프 쪽이고,
  API 호출이 없어 캐시된 그래프만으로 전수 계산된다.

⚠️ 순환출자 탐색은 경로 열거라 고차수 노드에서 폭발한다. `--max-paths` 로 상한을
   두고, 상한에 걸린 노드 수를 반드시 출력한다 — 조용히 자르면 "고리 없음" 과
   "너무 커서 못 셈" 이 구분되지 않는다.

사용:
    uv run python scripts/build_graph_baseline.py
"""
from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict, deque
from pathlib import Path

OUT = Path("data/baseline_graph.json")


def count_cycles(adj: dict[str, set[str]], start: str, max_len: int,
                 max_paths: int) -> tuple[int, bool]:
    """(고리 수, 상한에 걸렸는가). 상한 도달은 숨기지 않는다."""
    found: set[tuple[str, ...]] = set()
    queue: deque[list[str]] = deque([[start]])
    explored = 0
    while queue:
        explored += 1
        if explored > max_paths:
            return len(found), True
        path = queue.popleft()
        if len(path) > max_len:
            continue
        for nxt in adj.get(path[-1], ()):
            if nxt == start and len(path) >= 3:
                found.add(tuple(sorted(path)))
            elif nxt not in path:
                queue.append([*path, nxt])
    return len(found), False


def summarize(values: list[int]) -> dict[str, float | int]:
    vs = sorted(values)
    n = len(vs)
    q = lambda p: vs[min(int(p * n), n - 1)]  # noqa: E731
    return {
        "n": n,
        "zero_ratio": round(sum(1 for v in vs if v == 0) / n, 4) if n else 0.0,
        "median": statistics.median(vs) if vs else 0,
        "p90": q(0.90), "p95": q(0.95), "p99": q(0.99), "max": vs[-1] if vs else 0,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--graph", default="data/graph_closed.json")
    p.add_argument("--max-len", type=int, default=6)
    p.add_argument("--max-paths", type=int, default=200_000)
    p.add_argument("--hops", type=int, default=2)
    p.add_argument("--top-chokepoints", type=int, default=12)
    args = p.parse_args(argv)

    raw = json.loads(Path(args.graph).read_text(encoding="utf-8"))["edges"]
    edges = [(a, b) for a, b, _ in raw]
    nodes = sorted({v for e in edges for v in e})

    adj: dict[str, set[str]] = defaultdict(set)
    und: dict[str, set[str]] = defaultdict(set)
    for a, b in edges:
        adj[a].add(b)
        und[a].add(b)
        und[b].add(a)

    import igraph as ig
    from dartweave.structure.project import project
    g = project([(a, b, "R") for a, b in edges], undirected=True)
    g.simplify()
    ranked = sorted(zip(g.vs["corp_code"], g.betweenness()), key=lambda x: -x[1])
    chokes = {c for c, _ in ranked[: args.top_chokepoints]}

    cycles, mutual, near, capped = [], [], [], 0
    for i, n in enumerate(nodes, 1):
        c, hit_cap = count_cycles(adj, n, args.max_len, args.max_paths)
        capped += hit_cap
        cycles.append(c)
        mutual.append(len(adj.get(n, set()) & {s for s, t in edges if t == n}))
        # 무방향 BFS 로 홉수 안의 공동 의존점 수
        dist, q_, seen = {n: 0}, deque([n]), 0
        while q_:
            cur = q_.popleft()
            if dist[cur] >= args.hops:
                continue
            for nx in und.get(cur, ()):
                if nx in dist:
                    continue
                dist[nx] = dist[cur] + 1
                if nx in chokes:
                    seen += 1
                q_.append(nx)
        near.append(seen)
        if i % 300 == 0:
            print(f"  {i}/{len(nodes)}")

    result = {
        "nodes": len(nodes), "edges": len(edges),
        "max_cycle_len": args.max_len, "hops": args.hops,
        "capped_nodes": capped,
        "cycles": summarize(cycles),
        "mutual": summarize(mutual),
        "near_chokepoint": summarize(near),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"\n그래프 {len(nodes):,}개사 · 엣지 {len(edges):,}")
    if capped:
        print(f"⚠️  경로 상한에 걸린 노드 {capped}개 — 그 노드의 고리 수는 하한이다")
    for key, label in (("cycles", "순환출자 고리"), ("mutual", "상호 지분 보유"),
                       ("near_chokepoint", f"{args.hops}홉 내 공동의존점")):
        d = result[key]
        print(f"\n{label}")
        print(f"  0인 회사 {d['zero_ratio']:.1%} · 중위 {d['median']} · "
              f"p90 {d['p90']} · p95 {d['p95']} · p99 {d['p99']} · 최대 {d['max']}")
    print(f"\n→ {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
