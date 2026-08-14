"""층위 + 중심성 — 방향이 필요한 지표. 경계가 닫힌 뒤에만 계산한다.

군집(누구와 뭉치나)과 층위(공급망 어디쯤)는 다른 질문이다. 커뮤니티 탐지는 엣지 밀도만
보므로 계열사끼리 뭉치지 밸류체인 단계를 답하지 않는다. 층위는 방향 그래프의 위상에서
나온다 — 그래서 별도 모듈이고, 별도라는 사실 자체가 AC-4 의 분리 증거다.

경계 게이트가 여기에만 걸리는 이유: 실측상 군집은 경계에 견디지만(효과크기
+0.1211→+0.1305) 방향 지표는 뒤집힌다(출차수 1위 한화→태영건설).
"""
from __future__ import annotations

from dataclasses import dataclass

import igraph as ig

from dartweave.structure.project import BoundaryReport


class BoundaryNotClosed(RuntimeError):
    """경계가 열린 상태에서 층위·중심성을 요구했을 때."""


@dataclass(frozen=True)
class Topology:
    in_degree: dict[str, int]
    out_degree: dict[str, int]
    depth: dict[str, float]
    betweenness: dict[str, float]
    boundary_ratio: float


# ⚠️ RISK(breaking): 경계 게이트를 풀거나 우회 경로를 만들면 출차수 1위가 뒤바뀐 채로
# 보고된다(실측: 한화 85 → 태영건설 119). 군집은 경계에 견디지만 방향 지표는 안 견딘다
# — 그래서 게이트가 이 함수에만 걸려 있고, 이 비대칭이 D2 의 내용이다.
# — by main(3-checklist: 공개 반환 계약 / 실패 경로)
def topology(
    g: ig.Graph, boundary: BoundaryReport, *, max_boundary_ratio: float
) -> Topology:
    if not boundary.is_closed(max_ratio=max_boundary_ratio):
        raise BoundaryNotClosed(
            f"경계 비율 {boundary.ratio:.1%} > 허용 {max_boundary_ratio:.1%} — "
            "층위·중심성은 산출하지 않는다. 경계 노드의 신고를 먼저 수집할 것."
        )

    codes = list(g.vs["corp_code"])
    outd = g.degree(mode="out")
    ind = g.degree(mode="in")
    und = g.copy()
    und.to_undirected(combine_edges="ignore")
    und.simplify()
    btw = und.betweenness()

    # ⚠️ RISK(side-effect): 고립 노드(입출차수 모두 0)도 0.0 을 받는다 — 값으로만
    # 보면 '순수 상류' 와 구분되지 않는다. 지금은 경계가 닫힌 그래프만 들어와서
    # 고립 노드가 거의 없지만, 렌즈를 좁게 걸면 생길 수 있다. 평균 깊이를 낼 때
    # metrics.py 는 이 값을 그대로 평균 내므로 하류 쪽으로 편향될 수 있다.
    # — by main(3-checklist: 경계값 / 없는 값을 0으로 채움)
    # 공급 깊이: 입차수 비중이 높을수록 하류. 0(순수 상류) ~ 1(순수 하류).
    depth = {}
    for i, c in enumerate(codes):
        total = ind[i] + outd[i]
        depth[c] = (ind[i] / total) if total else 0.0

    return Topology(
        in_degree=dict(zip(codes, ind)),
        out_degree=dict(zip(codes, outd)),
        depth=depth,
        betweenness=dict(zip(codes, btw)),
        boundary_ratio=boundary.ratio,
    )
