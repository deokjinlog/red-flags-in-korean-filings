"""analyze() — 게이트 두 개가 계산 앞을 막는다.

게이트를 뒤에 두면 이미 나온 결과를 보고 판단하게 되어 사후 합리화가 들어온다.
요구사항 결정 11의 *"일단 돌려보고 나중에 판단 금지"* 를 구조로 강제한다.

CLI 는 이 함수를 부르는 껍데기다 — 층0 의 run_stage.py 가 init_schema 를 무조건
호출해 DB 없이 아무 단계도 못 돌던 갭(CH-20260813-015)을 반복하지 않기 위해서다.
"""
from __future__ import annotations

from dataclasses import dataclass

from dartweave.structure.cluster import cluster, compare_objectives
from dartweave.structure.evidence import EvidenceBlock, Scope, Thresholds
from dartweave.structure.lens import resolve_lens, select_indices
from dartweave.structure.metrics import cluster_metrics
from dartweave.structure.nullmodel import degree_preserving_null
from dartweave.structure.project import boundary_of, project
from dartweave.structure.sensitivity import (
    DEFAULT_MAX_RATIO,
    coefficient_sweep,
    resolution_sweep,
)
from dartweave.structure.topology import BoundaryNotClosed, topology
from dartweave.structure.verdict import MIN_EFFECT, MIN_Z, decide
from dartweave.structure.weight import EdgeEvidence, edge_weights

OUTLIER_MULTIPLE = 2.0  # 최상위 의존도가 중앙값의 이 배를 넘으면 "편차 있음"


class QualityGateFailed(RuntimeError):
    """층0 품질이 임계 미만 — 그 위에서 계산한 의존도는 의미가 없다."""


@dataclass(frozen=True)
class AnalysisConfig:
    min_corporate_resolution_rate: float = 0.8
    max_boundary_ratio: float = 0.0
    resolution: float = 1.0
    cpm_resolution: float = 0.005
    null_runs: int = 20
    sweep_max_ratio: float = DEFAULT_MAX_RATIO
    # 기본은 False — 경계가 열려도 **군집 결과는 돌려준다**. 실측상 군집은 경계에
    # 견디고(효과크기 +0.1211→+0.1305) 방향 지표만 뒤집히므로, 통째로 거부하면
    # 멀쩡한 결과까지 버리게 된다. 실데이터의 경계 비율은 한 번 닫고도 48.6% 였다.
    # 층위가 반드시 필요한 호출부만 True 로 켜서 예외를 받는다.
    require_topology: bool = False
    fiscal_year: str = "2024"
    industry: str = "미지정"


def _has_outlier(ratios: list[float]) -> bool:
    if len(ratios) < 2:
        return False
    ordered = sorted(ratios, reverse=True)
    mid = ordered[len(ordered) // 2]
    return mid > 0 and ordered[0] >= mid * OUTLIER_MULTIPLE


# ⚠️ RISK(breaking): 게이트 두 개는 **계산 앞**에 있어야 한다. 뒤로 옮기면 이미 나온
# 결과를 보고 통과 여부를 정하게 되어 사후 합리화가 들어온다 — 이 층이 막으려는 게
# 정확히 그것이다(요구사항 결정 11).
#
# ⚠️ RISK(side-effect): `require_topology` 기본값이 False 라 경계가 열리면 **조용히
# 부분 산출**된다. 이게 의도인 이유는 실데이터 경계가 48.6% 라 통째 거부하면 아무것도
# 못 내기 때문이지만, 소비자가 `topology_computed` 를 안 보면 `mean_supply_depth: null`
# 을 "깊이 0" 으로 오독한다. 층2 화면은 이 플래그를 반드시 렌더할 것.
# — by main(3-checklist: 복잡한 분기 / 공개 반환 계약 / 조용한 축소)
def analyze(
    edges: list[tuple[str, str, str]],
    *,
    interior: set[str],
    lens_name: str,
    corporate_resolution_rate: float,
    evidence: list[EdgeEvidence] | None = None,
    config: AnalysisConfig | None = None,
) -> EvidenceBlock:
    """`evidence` 는 `edges` 와 **같은 순서의 평행 리스트**다.

    주면 가중 실행 + 겹2 계수 스윕(AC-8)이 돌고, 안 주면 무가중 실행된다.
    """
    cfg = config or AnalysisConfig()
    if evidence is not None and len(evidence) != len(edges):
        raise ValueError(
            f"evidence({len(evidence)}) 와 edges({len(edges)}) 길이가 다르다 — "
            "가중치가 엉뚱한 엣지에 붙는다."
        )

    # [G1] 품질 게이트 — 계산 전에 막는다.
    if corporate_resolution_rate < cfg.min_corporate_resolution_rate:
        raise QualityGateFailed(
            f"법인 해소율 {corporate_resolution_rate:.2f} < "
            f"임계 {cfg.min_corporate_resolution_rate:.2f} — 분석을 실행하지 않는다."
        )

    lens = resolve_lens(lens_name)
    idx = select_indices(edges, lens)
    kept = [edges[i] for i in idx]
    kept_ev = [evidence[i] for i in idx] if evidence is not None else None
    boundary = boundary_of(kept, interior)

    weights = edge_weights(kept_ev) if kept_ev is not None else None
    und = project(kept, undirected=True, weights=weights)
    nat = project(kept, undirected=False)

    # [G2] 경계 게이트 — 층위·중심성만 막는다. 군집은 경계에 견딘다.
    # 거부는 예외가 아니라 **미산출 + 표시**로 표현한다. 예외로 끝내면 AC-14 가
    # 요구하는 "경계 비율이 출력에 명시된다" 를 지킬 출력 자체가 사라진다.
    try:
        depth = topology(
            nat, boundary, max_boundary_ratio=cfg.max_boundary_ratio
        ).depth
        topo_computed = True
    except BoundaryNotClosed:
        if cfg.require_topology:
            raise
        depth, topo_computed = {}, False

    clu = cluster(und, objective="modularity", resolution=cfg.resolution, seed=1)
    codes = list(und.vs["corp_code"])
    membership = dict(zip(codes, clu.membership))

    rows = cluster_metrics(kept, membership, depth=depth)
    null = degree_preserving_null(und, runs=cfg.null_runs, seed=1)
    sweep = resolution_sweep(und, max_ratio=cfg.sweep_max_ratio)
    cmp_obj = compare_objectives(
        und, resolution=cfg.resolution, cpm_resolution=cfg.cpm_resolution
    )

    # AC-8 — 근거가 있을 때만 계수를 흔들 수 있다. 없으면 흔들 대상이 없으므로
    # "버텼다" 가 아니라 **검사하지 않았다** 로 두고 결론 판정에서 제외한다.
    if kept_ev is not None:
        coef = coefficient_sweep(
            kept, kept_ev, resolution=cfg.resolution, max_ratio=cfg.sweep_max_ratio
        )
        coef_holds, coef_ratio = coef.holds, coef.largest_ratio
        stability_holds = sweep.holds and coef.holds
    else:
        coef_holds, coef_ratio = False, 1.0
        stability_holds = sweep.holds

    verdict = decide(
        z=null.z,
        effect_size=null.effect_size,
        sweep_holds=stability_holds,
        has_outlier=_has_outlier([r.dependency_ratio for r in rows]),
    )

    return EvidenceBlock(
        lens=lens.name,
        include_types=sorted(lens.include),
        objective="modularity",
        resolution=cfg.resolution,
        clusters=rows,
        modularity=null.actual,
        null_mean=null.mean,
        null_sd=null.sd,
        null_runs=null.runs,
        null_swaps_failed=null.swaps_failed,
        cpm_clusters=cmp_obj["cpm_clusters"],
        cpm_delta=cmp_obj["delta"],
        sweep_holds=sweep.holds,
        sweep_ratio=sweep.largest_ratio,
        coef_sweep_holds=coef_holds,
        coef_sweep_ratio=coef_ratio,
        corporate_resolution_rate=corporate_resolution_rate,
        topology_computed=topo_computed,
        scope=Scope(
            industry=cfg.industry,
            companies=len({v for e in kept for v in e[:2]}),
            disclosures=len(kept),
            fiscal_year=cfg.fiscal_year,
            boundary_ratio=boundary.ratio,
        ),
        thresholds=Thresholds(
            min_corporate_resolution_rate=cfg.min_corporate_resolution_rate,
            max_boundary_ratio=cfg.max_boundary_ratio,
            min_effect_size=MIN_EFFECT,
            min_z=MIN_Z,
            sweep_max_ratio=cfg.sweep_max_ratio,
        ),
        verdict=verdict,
    )
