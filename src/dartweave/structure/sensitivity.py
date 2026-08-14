"""민감도 스윕 — 부록이 아니라 결론 판정의 입력이다.

실측: 해상도 0.5→2.0 에서 최대 군집이 126→69 로 반토막 났다. *"가장 큰 군집이 N개사"*
류 결론은 이 구간을 못 버틴다. 특정 구간에서만 성립하는 결론은 파라미터를 잘 골라서
나온 우연이므로 보고하지 않는다.

**판정 지표를 비중 차이가 아니라 배율로 재는 이유.** 처음엔 최대군집 비중의 절대
차이(spread)로 쟀는데, 그러면 위 실측 사례를 **못 잡는다** — 1,490 노드에서 126→69 는
비중으로 0.085→0.046, 차이가 0.038 밖에 안 돼서 어떤 느슨한 임계도 통과한다.
군집이 반토막 났는데 게이트가 조용한 것이다. 크기가 절반이 된 건 배율로 봐야
드러난다(1.83배). 그래서 최대군집 비중의 **최대/최소 비율**로 판정한다.
"""
from __future__ import annotations

from dataclasses import dataclass

import igraph as ig

from dartweave.structure.cluster import cluster
from dartweave.structure.project import project
from dartweave.structure.weight import EdgeEvidence, edge_weights
from dartweave.trust.weight import Coefficients

RESOLUTIONS: tuple[float, ...] = (0.5, 0.8, 1.0, 1.2, 1.5, 2.0)
# 최대군집 크기의 허용 배율. 실측 접지 — 안정 구조는 1.00배(합성 확인), 실데이터의
# 문제 사례는 1.83배, 무구조 그래프는 9.05배였다. 1.5 는 그 사이를 가른다.
DEFAULT_MAX_RATIO = 1.5

# AC-8 — 겹2 계수는 임의값이다. 결론이 그 임의값에 기대고 있으면 결론이 아니다.
# ⚠️ RISK(side-effect): 계수 축을 전수 조합하면 폭발한다(4축 × 각 3값 = 81회 클러스터링).
# 여기는 **축별 독립 5케이스**이고 계수 간 상호작용은 검사하지 않는다 — 그 사실이
# 근거 블록의 `label` 로 드러나야 "무엇을 검사했고 무엇을 안 했는지" 를 알 수 있다.
# — by main(3-checklist: 조합 폭발 / 검사 범위 오독)
COEFFICIENT_CASES: tuple[tuple[str, Coefficients], ...] = (
    ("baseline", Coefficients()),
    ("cross_confirm_off", Coefficients(cross_confirm_bonus=1.0)),
    ("cross_confirm_strong", Coefficients(cross_confirm_bonus=3.0)),
    ("mention_flat", Coefficients(mention_step=0.0)),
    ("mention_steep", Coefficients(mention_step=0.3, mention_cap=3.0)),
)


@dataclass(frozen=True)
class SweepPoint:
    resolution: float
    n_clusters: int
    largest_cluster: int
    largest_share: float
    label: str = ""


@dataclass(frozen=True)
class SweepResult:
    points: list[SweepPoint]
    holds: bool
    largest_ratio: float


def stability_ratio(points: list[SweepPoint]) -> float:
    """최대군집 비중의 최대/최소 배율. 1.0 이면 스윕 내내 꿈쩍 안 했다는 뜻.

    비중의 절대 차이를 쓰면 안 된다 — 큰 그래프에서는 군집이 반토막 나도 차이가
    0.04 수준이라 어떤 임계도 통과한다(실측).
    """
    shares = [p.largest_share for p in points if p.largest_share > 0]
    if not shares:
        return 1.0
    return max(shares) / min(shares)


def resolution_sweep(
    g: ig.Graph,
    *,
    resolutions: tuple[float, ...] = RESOLUTIONS,
    max_ratio: float = DEFAULT_MAX_RATIO,
) -> SweepResult:
    points: list[SweepPoint] = []
    for res in resolutions:
        points.append(_point(g, resolution=res, label=f"resolution={res}"))
    return _summarize(points, max_ratio)


def coefficient_sweep(
    edges: list[tuple[str, str, str]],
    evidence: list[EdgeEvidence],
    *,
    resolution: float = 1.0,
    max_ratio: float = DEFAULT_MAX_RATIO,
    cases: tuple[tuple[str, Coefficients], ...] = COEFFICIENT_CASES,
) -> SweepResult:
    """겹2 계수를 흔들어도 결론이 버티는가 (AC-8).

    해상도 스윕과 형태는 같지만 흔드는 대상이 다르다 — 이쪽은 **가중치를 다시
    계산해서** 그래프를 새로 만든다. 계수가 바뀌면 엣지 굵기가 바뀌고, 굵기가
    바뀌면 군집 경계가 움직인다.
    """
    points: list[SweepPoint] = []
    for label, coef in cases:
        g = project(edges, undirected=True, weights=edge_weights(evidence, coef))
        points.append(_point(g, resolution=resolution, label=label))
    return _summarize(points, max_ratio)


def _point(ig_graph: ig.Graph, *, resolution: float, label: str) -> SweepPoint:
    r = cluster(ig_graph, objective="modularity", resolution=resolution, seed=1)
    sizes: dict[int, int] = {}
    for m in r.membership:
        sizes[m] = sizes.get(m, 0) + 1
    largest = max(sizes.values()) if sizes else 0
    return SweepPoint(
        resolution=resolution,
        n_clusters=r.n_clusters,
        largest_cluster=largest,
        largest_share=largest / ig_graph.vcount() if ig_graph.vcount() else 0.0,
        label=label,
    )


def _summarize(points: list[SweepPoint], max_ratio: float) -> SweepResult:
    ratio = stability_ratio(points)
    return SweepResult(points=points, holds=ratio <= max_ratio, largest_ratio=ratio)
