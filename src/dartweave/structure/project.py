"""투영 두 벌 + 경계 판정.

Leiden 은 UNDIRECTED 를 요구하고 층위는 방향이 필요하다. 저장은 하나, 투영에서 갈린다.

경계 판정이 여기 있는 이유 (AC-14): 자기 신고가 없는 노드는 자기 쪽 엣지가 통째로
빠져 있어 출입차수가 인위적으로 왜곡된다. 실측 — 경계 열림에서 출차수 1위는 한화(85)
였는데, 닫고 나니 태영건설(119) 이었다. **경계 열린 상태의 방향 지표는 틀린 결론을 낸다.**
"""
from __future__ import annotations

from dataclasses import dataclass

import igraph as ig


@dataclass(frozen=True)
class BoundaryReport:
    total: int
    boundary: int

    @property
    def ratio(self) -> float:
        return self.boundary / self.total if self.total else 0.0

    def is_closed(self, *, max_ratio: float) -> bool:
        return self.ratio <= max_ratio


def boundary_of(
    edges: list[tuple[str, str, str]], interior: set[str]
) -> BoundaryReport:
    nodes = {v for e in edges for v in e[:2]}
    return BoundaryReport(total=len(nodes), boundary=len(nodes - interior))


def project(
    edges: list[tuple[str, str, str]],
    *,
    undirected: bool,
    weights: list[float] | None = None,
) -> ig.Graph:
    verts = sorted({v for e in edges for v in e[:2]})
    idx = {v: i for i, v in enumerate(verts)}
    g = ig.Graph(directed=True)
    g.add_vertices(len(verts))
    g.vs["corp_code"] = verts
    g.add_edges([(idx[a], idx[b]) for a, b, _ in edges])
    g.es["type"] = [t for _, _, t in edges]
    if weights is not None:
        g.es["weight"] = weights
    if undirected:
        # ⚠️ `combine_edges="sum"` 는 문자열 속성 `type` 에서 죽는다 (실측:
        # TypeError "product can only be invoked on numeric attributes").
        # 속성별로 지정해야 하고, `weight` 가 없어도 이 형태는 안전하다.
        g.to_undirected(combine_edges={"weight": "sum", "type": "first"})
    return g
