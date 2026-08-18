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
    p.add_argument("--as-of", required=True,
                   help="특징 계산 시점. 쉼표로 여러 개 주면 기업-연도 패널로 합친다")
    p.add_argument("--within-days", type=int, default=365, help="라벨 관찰 창")
    p.add_argument("--runs", type=int, default=2000)
    p.add_argument("--unit", choices=("company", "company-year"), default="company",
                   help="company=회사당 1관측(기본·독립성 유지) · "
                        "company-year=기업-연도 패널(같은 회사가 여러 번 들어가 p가 부풀려짐)")
    args = p.parse_args(argv)

    points = [t.strip() for t in args.as_of.split(",") if t.strip()]
    panel: dict[str, list[tuple[str, bool]]] = {s: [] for s in SIGNALS}
    n_obs = n_ev = 0

    for t in points:
        with Session(create_engine(args.db)) as s:
            latest = latest_edges_at(s, t)
            events = events_after(s, t, within_days=args.within_days)
        edges = [(f.source_corp_code, f.target_corp_code, f.rel_type)
                 for f in latest.values()]
        if not edges:
            print(f"  {t}: 알 수 있었던 관계 없음 — 건너뜀")
            continue
        if events:
            assert_no_look_ahead(t, min(e.rcept_dt for e in events))

        g = project(edges, undirected=True); g.simplify()
        ranked = sorted(zip(g.vs["corp_code"], g.betweenness()), key=lambda x: -x[1])
        nodes, feats = build_features(edges, {c for c, _ in ranked[:12]})
        distressed = {e.corp_code for e in events}
        n_obs += len(nodes)
        n_ev += len(distressed & set(nodes))
        for sig in SIGNALS:
            for n in nodes:
                panel[sig].append((n, n in distressed)) if n in feats[sig] else None
        # 대조군은 신호별로 따로 담는다
        for sig in SIGNALS:
            panel.setdefault(sig + "_ctl", []).extend(
                (n, n in distressed) for n in nodes if n not in feats[sig])
        print(f"  {t}: 대상 {len(nodes):,}사 · 관계 {len(edges):,} · "
              f"창 안 부실 {len(distressed & set(nodes)):,}사")

    if args.unit == "company":
        # 같은 회사를 한 번만 센다. 관측 독립성이 회복된다.
        # ⚠️ 이 구분이 결정적이다. 기업-연도로 세면 순환출자가 ×4.18 · p=0.0005 로
        #    유의하게 나왔는데, 회사 단위로 다시 세니 신호군 부실이 10건뿐이라
        #    TOO_FEW 였다. 같은 회사를 4번 센 것이 만든 허수였다.
        for sig in SIGNALS:
            for key in (sig, sig + "_ctl"):
                by_corp: dict[str, bool] = {}
                for corp, d in panel[key]:
                    by_corp[corp] = by_corp.get(corp, False) or d
                panel[key] = list(by_corp.items())
        n_obs = len({c for sig in SIGNALS for c, _ in panel[sig] + panel[sig + "_ctl"]})
        n_ev = len({c for sig in SIGNALS for c, d in panel[sig] + panel[sig + "_ctl"] if d})

    label = "회사" if args.unit == "company" else "기업-연도"
    print(f"\n{label} 관측 {n_obs:,} · 부실 {n_ev:,} · 시점 {len(points)}개")
    if args.unit == "company-year" and len(points) > 1:
        print("⚠️ 같은 회사가 여러 시점에 들어가 관측이 독립이 아니다 — p 값이 부풀려진다.")
        print("   실측: 순환출자가 여기서는 ×4.18·p=0.0005 였지만 회사 단위로는 TOO_FEW.\n")

    for sig in SIGNALS:
        have = [d for _, d in panel[sig]]
        not_have = [d for _, d in panel[sig + "_ctl"]]
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
