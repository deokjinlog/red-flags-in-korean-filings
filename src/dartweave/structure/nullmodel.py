"""차수 보존 귀무모형.

모듈러리티에 절대 기준을 쓰지 않는 이유는 희소 그래프가 무작위여도 높게 나오기
때문이다. 실측 — 실제 0.8535 인데 **귀무모형이 이미 0.7230**. 절대 기준(0.3)을 썼으면
"매우 우수" 라고 판단했을 것이고, 실제 신호는 효과크기 +0.1305 뿐이다.

셔플은 반드시 차수를 보존해야 한다. 완전 무작위는 허브 구조까지 파괴해서 귀무
모듈러리티를 부당하게 낮추고, 그러면 "구조가 없어서" 가 아니라 "허브를 없애서" 나온
숫자로 승리를 선언하게 된다.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass

import igraph as ig
import networkx as nx


@dataclass(frozen=True)
class NullResult:
    actual: float
    mean: float
    sd: float
    runs: int
    degree_preserved: bool
    swaps_failed: int

    @property
    def z(self) -> float:
        return (self.actual - self.mean) / self.sd if self.sd else float("inf")

    @property
    def effect_size(self) -> float:
        """실제 - 귀무. z 는 표준편차가 작으면 부풀려지므로 이걸 함께 본다."""
        return self.actual - self.mean


def _to_nx(g: ig.Graph) -> nx.Graph:
    h = nx.Graph()
    h.add_nodes_from(range(g.vcount()))
    h.add_edges_from([(e.source, e.target) for e in g.es])
    return h


# ⚠️ RISK(side-effect): `runs` 가 `sd` 를 좌우하고 `sd` 가 `z` 를 좌우한다. 반복이
# 적으면 z 가 요동치므로 출력에 반복수를 명시한다(AC-5). 그래서 z 단독으로 판정하지
# 않고 효과크기를 함께 본다.
# 셔플이 실패한 회차도 점수에 들어간다(섞이다 만 그래프의 모듈러리티). 이건 귀무
# 평균을 실제값 쪽으로 끌어올려 **효과크기를 줄이는** 방향이라 보수적이다 — 거짓
# 채택이 아니라 거짓 기각 쪽으로 틀린다. 다만 그 사실이 숫자만 봐서는 안 보이므로
# `swaps_failed` 를 반드시 근거 블록까지 실어 보낼 것.
# — by main(3-checklist: 복잡한 분기 / 경계값)
def degree_preserving_null(
    g: ig.Graph, *, runs: int = 20, seed: int = 1
) -> NullResult:
    actual = g.community_leiden(
        objective_function="modularity", n_iterations=10
    ).modularity
    base = _to_nx(g)
    before = sorted(d for _, d in base.degree())

    scores: list[float] = []
    preserved = True
    failed = 0
    for _ in range(runs):
        h = base.copy()
        try:
            nx.double_edge_swap(
                h,
                nswap=h.number_of_edges() * 2,
                max_tries=h.number_of_edges() * 50,
                seed=seed,
            )
        # ⚠️ 둘은 형제 예외다. `NetworkXAlgorithmError` 는 `NetworkXError` 의
        # 하위가 **아니라서** 하나만 잡으면 4노드 미만 그래프에서 통째로 터진다
        # (실측: "Graph has fewer than four nodes" 는 NetworkXError).
        except (nx.NetworkXError, nx.NetworkXAlgorithmError):
            failed += 1
        if sorted(d for _, d in h.degree()) != before:
            preserved = False
        gi = ig.Graph(n=h.number_of_nodes(), edges=list(h.edges()), directed=False)
        scores.append(
            gi.community_leiden(
                objective_function="modularity", n_iterations=10
            ).modularity
        )

    return NullResult(
        actual=actual,
        mean=statistics.mean(scores),
        sd=statistics.stdev(scores) if len(scores) > 1 else 0.0,
        runs=runs,
        degree_preserved=preserved,
        swaps_failed=failed,
    )
