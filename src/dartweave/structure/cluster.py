"""군집 — Leiden. Louvain 은 쓰지 않는다.

Louvain 은 연결조차 안 된 군집을 만들 수 있다(최대 25% 불량 연결, 16% 분리).
Leiden 은 연결성을 증명으로 보장한다 (Traag et al., Sci Rep 9:5233, 2019).

CPM 병행이 필수인 이유: 모듈러리티 최적화는 네트워크 크기에 의존하는 규모보다 작은
모듈을 원리적으로 못 본다 (Fortunato & Barthélemy, PNAS 104(1), 2007).
실측 — CPM(0.005) 52군집 vs 모듈러리티 38군집. **14개를 놓친다.**
"""
from __future__ import annotations

import random
from dataclasses import dataclass

import igraph as ig

N_ITERATIONS = 10


@dataclass(frozen=True)
class ClusterResult:
    membership: list[int]
    modularity: float
    n_clusters: int
    objective: str
    resolution: float


# ⚠️ RISK(race): `ig.set_random_number_generator` 는 **프로세스 전역**이다. igraph 에
# 호출별 RNG 인자가 없어 우회로가 없다. 스윕이나 귀무 반복을 스레드로 병렬화하면
# 시드가 경합해 재현성이 깨진다 — 병렬화가 필요하면 프로세스 분리가 유일한 답이다.
# 부수 효과 하나 더: `seed=None` 호출은 깨끗한 기본 상태가 아니라 **직전 호출이
# 남긴 상태**를 물려받는다. 지금 스위트는 단일 프로세스·고정 순서라 안전하다.
# — by main(3-checklist: 공유 상태)
def cluster(
    g: ig.Graph,
    *,
    objective: str = "modularity",
    resolution: float = 1.0,
    seed: int | None = None,
) -> ClusterResult:
    if seed is not None:
        # ⚠️ 전역 상태다. 병렬화하면 시드가 경합한다 (§2 참조).
        ig.set_random_number_generator(random.Random(seed))
    weights = g.es["weight"] if "weight" in g.es.attributes() else None
    vc = g.community_leiden(
        objective_function=objective,
        resolution=resolution,
        weights=weights,
        n_iterations=N_ITERATIONS,
    )
    return ClusterResult(
        membership=list(vc.membership),
        modularity=g.modularity(vc.membership, weights=weights),
        n_clusters=len(vc),
        objective=objective,
        resolution=resolution,
    )


def compare_objectives(
    g: ig.Graph, *, resolution: float = 1.0, cpm_resolution: float = 0.005
) -> dict[str, int]:
    """모듈러리티가 놓친 군집 수를 드러낸다. 차이 자체가 보고 대상이다."""
    m = cluster(g, objective="modularity", resolution=resolution)
    c = cluster(g, objective="CPM", resolution=cpm_resolution)
    return {
        "modularity_clusters": m.n_clusters,
        "cpm_clusters": c.n_clusters,
        "delta": c.n_clusters - m.n_clusters,
    }
