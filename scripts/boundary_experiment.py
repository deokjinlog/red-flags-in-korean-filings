"""수집 경계 닫기 실험 — 층위·중심성이 진짜인지 경계 인공물인지 가른다.

배경:
  1홉 확장으로 만든 그래프는 대상 기업만 자기 신고를 내고 나머지는 상대편으로만
  등장한다. 그래서 출차수(한화 87)와 입차수(최대 9)가 극단적으로 비대칭인데,
  이건 실제 구조가 아니라 **수집 경계**다. 층1의 "공급 깊이·밸류체인 층위" 분석은
  이 경계를 닫기 전에는 의미가 없다.

방법:
  BEFORE(경계 열림) / AFTER(경계 닫음) 지표를 같은 방식으로 재고, 저차수·고매개
  노드가 살아남는지 본다. 살아남으면 진짜 구조적 급소, 무너지면 경계 인공물.

산출물은 `data/` 에 남긴다 (`.gitignore` 대상 — /tmp 정리에 날아가지 않게).
"""
from __future__ import annotations

import json
import statistics
from pathlib import Path

import igraph as ig
import networkx as nx

from dartweave.config import Settings
from dartweave.dart.client import DartClient
from dartweave.dart.corpcode import parse_corpcode_zip
from dartweave.parse.structured_rel import parse_investment, parse_major_shareholder
from dartweave.resolve.resolver import Resolver

YEAR, REPRT = "2024", "11011"
NULL_RUNS = 20
DATA = Path(__file__).resolve().parents[1] / "data"

SEED_NAMES = [
    "삼성전자", "삼성전기", "한미반도체", "리노공업", "이오테크닉스",
    "주성엔지니어링", "티씨케이", "솔브레인", "동진쎄미켐", "네패스",
    "심텍", "하나마이크론", "에스에프에이", "테스", "유진테크",
    "피에스케이", "월덱스", "케이씨텍", "원익홀딩스", "덕산네오룩스",
    "이녹스첨단소재", "미코", "고영", "에프에스티", "엘오티베큠",
    "제우스", "에스티아이", "테크윙", "인텍플러스", "티에스이",
    "두산테스나", "하나머티리얼즈", "SK", "LG", "GS",
    "CJ", "롯데지주", "한화", "두산", "효성",
    "코오롱", "LS", "HD현대", "삼양홀딩스",
]


def _edges_of(client, resolver, code: str) -> list[tuple[str, str, str]]:
    out: list[tuple[str, str, str]] = []
    p = client.get_json(
        "hyslrSttus.json", {"corp_code": code, "bsns_year": YEAR, "reprt_code": REPRT}
    )
    for e in parse_major_shareholder(p):
        r = resolver.resolve(e.source_name, rcept_no=e.rcept_no)
        if r.corp_code and e.target_corp_code:
            out.append((r.corp_code, e.target_corp_code, "SHAREHOLDER"))
    p2 = client.get_json(
        "otrCprInvstmntSttus.json",
        {"corp_code": code, "bsns_year": YEAR, "reprt_code": REPRT},
    )
    for e in parse_investment(p2):
        r = resolver.resolve(e.target_name or "", rcept_no=e.rcept_no)
        if r.corp_code and e.source_corp_code:
            out.append((e.source_corp_code, r.corp_code, "INVESTS"))
    return out


def build(edges, names):
    verts = sorted({v for e in edges for v in e[:2]})
    idx = {v: i for i, v in enumerate(verts)}
    g = ig.Graph(directed=True)
    g.add_vertices(len(verts))
    g.vs["corp_code"] = verts
    g.vs["name"] = [names.get(v, v) for v in verts]
    g.add_edges([(idx[a], idx[b]) for a, b, _ in edges])
    return g


def null_modularity(und, runs=NULL_RUNS):
    """차수 보존 셔플. 완전 무작위는 허브까지 없애 부당하게 유리해진다."""
    nxg = nx.Graph()
    nxg.add_nodes_from(range(und.vcount()))
    nxg.add_edges_from([(e.source, e.target) for e in und.es])
    vals = []
    for _ in range(runs):
        h = nxg.copy()
        try:
            nx.double_edge_swap(
                h, nswap=h.number_of_edges() * 2,
                max_tries=h.number_of_edges() * 50, seed=1,
            )
        except nx.NetworkXAlgorithmError:
            pass
        gi = ig.Graph(n=h.number_of_nodes(), edges=list(h.edges()), directed=False)
        vals.append(
            gi.community_leiden(objective_function="modularity", n_iterations=5).modularity
        )
    return vals


def measure(tag: str, edges, names, interior: set[str]) -> dict[str, tuple[float, int]]:
    g = build(edges, names)
    und = g.copy()
    und.to_undirected(combine_edges="ignore")
    und.simplify()
    outd, ind, btw = g.degree(mode="out"), g.degree(mode="in"), und.betweenness()

    print(f"\n{'=' * 74}\n{tag}\n{'=' * 74}")
    inside = sum(1 for v in g.vs if v["corp_code"] in interior)
    print(f"노드 {g.vcount()} · 방향엣지 {g.ecount()} · 무방향 {und.ecount()}")
    print(f"내부(자기 신고 보유) {inside} · 경계(상대편으로만 등장) {g.vcount() - inside}")

    act = und.community_leiden(objective_function="modularity", n_iterations=10)
    nulls = null_modularity(und)
    mu = statistics.mean(nulls)
    sd = statistics.stdev(nulls) if len(nulls) > 1 else 0.0
    z = (act.modularity - mu) / sd if sd else float("inf")
    print(f"모듈러리티 {act.modularity:.4f} vs 귀무 {mu:.4f}±{sd:.4f} → "
          f"z={z:.1f} · 효과크기 {act.modularity - mu:+.4f} · 군집 {len(act)}")

    top_o = sorted(range(g.vcount()), key=lambda i: -outd[i])[:5]
    top_i = sorted(range(g.vcount()), key=lambda i: -ind[i])[:5]
    print(f"출차수 상위 {[(g.vs[i]['name'], outd[i]) for i in top_o]}")
    print(f"입차수 상위 {[(g.vs[i]['name'], ind[i]) for i in top_i]}")
    print(f"출/입 최대 비율 {max(outd)}/{max(ind)} = {max(outd) / max(max(ind), 1):.1f}배")

    print("\n매개중심성 상위 8")
    for i in sorted(range(und.vcount()), key=lambda i: -btw[i])[:8]:
        d = und.degree(i)
        loc = "내부" if und.vs[i]["corp_code"] in interior else "경계"
        mark = " ← 저차수·고매개" if d <= 10 else ""
        print(f"  {und.vs[i]['name']:<22} btw={btw[i]:>10,.0f} deg={d:>3} [{loc}]{mark}")

    return {v["corp_code"]: (btw[i], und.degree(i)) for i, v in enumerate(und.vs)}


def main() -> None:
    DATA.mkdir(exist_ok=True)
    base_f, closed_f = DATA / "graph_open.json", DATA / "graph_closed.json"

    client = DartClient(Settings.from_env().require_api_key(), min_interval=0.38)
    rows = parse_corpcode_zip(client.get_bytes("corpCode.xml", {}))
    names = {r.corp_code: r.corp_name for r in rows}
    listed = {r.corp_code for r in rows if r.stock_code}
    resolver = Resolver({r.corp_name: r.corp_code for r in rows}, aliases={})

    # ── 1홉 확장으로 내부 집합 만들기 ──
    seeds = {}
    for nm in SEED_NAMES:
        r = resolver.resolve(nm, rcept_no="seed")
        if r.corp_code:
            seeds[nm] = r.corp_code
    print(f"씨앗 해소 {len(seeds)}/{len(SEED_NAMES)}")

    if base_f.exists():
        payload = json.loads(base_f.read_text())
        base_edges = [tuple(e) for e in payload["edges"]]
        interior = set(payload["interior"])
        print(f"(캐시) 내부 {len(interior)}사 · 엣지 {len(base_edges)}")
    else:
        base_edges, frontier = [], set()
        for i, code in enumerate(seeds.values(), 1):
            es = _edges_of(client, resolver, code)
            base_edges.extend(es)
            for a, b, _ in es:
                frontier.update((a, b))
            if i % 10 == 0:
                print(f"  씨앗 {i}/{len(seeds)}", flush=True)
        interior = set(seeds.values()) | {c for c in frontier if c in listed}
        interior = set(sorted(interior)[:130])
        for i, code in enumerate(sorted(interior - set(seeds.values())), 1):
            base_edges.extend(_edges_of(client, resolver, code))
            if i % 25 == 0:
                print(f"  내부 확장 {i}", flush=True)
        base_edges = list(dict.fromkeys(base_edges))
        base_f.write_text(json.dumps(
            {"edges": base_edges, "interior": sorted(interior)}, ensure_ascii=False))
        print(f"내부 {len(interior)}사 · 엣지 {len(base_edges)}")

    before = measure("BEFORE — 경계 열림", base_edges, names, interior)

    # ── 경계 닫기 ──
    nodes = {v for e in base_edges for v in e[:2]}
    todo = sorted(nodes - interior)
    print(f"\n경계 닫기 대상 {len(todo)}사 (호출 {len(todo) * 2}건 예상)")

    if closed_f.exists():
        edges = [tuple(e) for e in json.loads(closed_f.read_text())["edges"]]
        print("(캐시 사용)")
    else:
        edges = list(base_edges)
        for i, code in enumerate(todo, 1):
            edges.extend(_edges_of(client, resolver, code))
            if i % 50 == 0:
                print(f"  {i}/{len(todo)}", flush=True)
        edges = list(dict.fromkeys(edges))
        closed_f.write_text(json.dumps({"edges": edges}, ensure_ascii=False))
    client.close()

    after = measure("AFTER — 경계 닫음", edges, names, interior | set(todo))

    print(f"\n{'=' * 74}\n판정 — 저차수·고매개 노드가 살아남았는가\n{'=' * 74}")
    cands = sorted(
        (c for c, (b, d) in before.items() if d <= 10 and b > 0),
        key=lambda c: -before[c][0],
    )[:6]
    for c in cands:
        b, a = before[c], after.get(c, (0.0, 0))
        verdict = "진짜 (유지)" if a[0] > b[0] * 0.5 else "경계 인공물 (붕괴)"
        print(f"  {names.get(c, c):<22} btw {b[0]:>10,.0f} → {a[0]:>10,.0f} · "
              f"deg {b[1]:>3} → {a[1]:>3}   {verdict}")


if __name__ == "__main__":
    main()
