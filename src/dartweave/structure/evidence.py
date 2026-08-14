"""근거 블록 — 층2 의 렌더 입력이자 층1 의 완료 판정.

원문 인용은 "해석이 다르다" 가 가능하지만 계산 내역은 그게 안 된다. 반박하려면
계산을 반박해야 한다. 그래서 이 층의 산출은 문장이 아니라 **수치 묶음**이다.

`scope` 가 빠지면 안 된다. 데이터가 좁은 건 결함이 아니지만 범위를 안 밝히고
일반화하는 건 결함이다.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from dartweave.structure.metrics import ClusterRow
from dartweave.structure.verdict import Verdict


# ⚠️ RISK(breaking): 이 구조체가 층2 의 렌더 계약이다. 필드를 지우거나 이름을 바꾸면
# 층2 화면이 조용히 빈칸을 그린다. 특히 `scope` 를 선택 필드로 만들면 안 된다 —
# 데이터가 좁은 건 결함이 아니지만 범위를 안 밝히고 일반화하는 건 결함이다.
# — by main(3-checklist: 공개 스키마 / 다운스트림 소비자)
@dataclass(frozen=True)
class Scope:
    industry: str
    companies: int
    disclosures: int
    fiscal_year: str
    boundary_ratio: float


@dataclass(frozen=True)
class Thresholds:
    """AC-12 — 임계값은 설정으로 정의되고 **출력에 명시**된다.

    코드에 매직넘버로 박히면 "왜 통과/반려됐는지" 를 산출물만 보고 알 수 없다.
    """

    min_corporate_resolution_rate: float
    max_boundary_ratio: float
    min_effect_size: float
    min_z: float
    sweep_max_ratio: float


@dataclass(frozen=True)
class EvidenceBlock:
    lens: str
    include_types: list[str]
    objective: str
    resolution: float
    clusters: list[ClusterRow]
    modularity: float
    null_mean: float
    null_sd: float
    null_runs: int
    null_swaps_failed: int
    cpm_clusters: int
    cpm_delta: int
    sweep_holds: bool
    sweep_ratio: float
    coef_sweep_holds: bool
    coef_sweep_ratio: float
    corporate_resolution_rate: float
    topology_computed: bool
    scope: Scope
    thresholds: Thresholds
    verdict: Verdict


def to_json(block: EvidenceBlock) -> str:
    return json.dumps(
        {
            "lens": {"name": block.lens, "include_types": block.include_types},
            "algorithm": {
                "name": "leiden",
                "objective": block.objective,
                "resolution": block.resolution,
                "n_clusters": len(block.clusters),
            },
            "clusters": [
                {
                    "id": c.cluster_id,
                    "nodes": c.nodes,
                    "internal_edges": c.internal_edges,
                    "external_edges": c.external_edges,
                    "dependency_ratio": c.dependency_ratio,
                    "mean_supply_depth": c.mean_supply_depth,
                }
                for c in block.clusters
            ],
            "verification": {
                "edges": {
                    "corporate_resolution_rate": block.corporate_resolution_rate
                },
                "structure": {
                    "modularity": block.modularity,
                    "null_mean": block.null_mean,
                    "null_sd": block.null_sd,
                    "runs": block.null_runs,
                    # 셔플이 실패한 회차. >0 이면 귀무모형이 덜 섞였다는 뜻이라
                    # 효과크기가 실제보다 작게 나온다 — 숫자만 봐선 안 보이므로 싣는다.
                    "swaps_failed": block.null_swaps_failed,
                    "effect_size": round(block.modularity - block.null_mean, 6),
                    "cpm_clusters": block.cpm_clusters,
                    "cpm_delta": block.cpm_delta,
                },
                "stability": {
                    "resolution": {
                        "holds": block.sweep_holds,
                        "largest_ratio": block.sweep_ratio,
                    },
                    "coefficients": {
                        "holds": block.coef_sweep_holds,
                        "largest_ratio": block.coef_sweep_ratio,
                    },
                },
            },
            "scope": {
                "industry": block.scope.industry,
                "companies": block.scope.companies,
                "disclosures": block.scope.disclosures,
                "fiscal_year": block.scope.fiscal_year,
                "boundary_ratio": block.scope.boundary_ratio,
            },
            "thresholds": {
                "min_corporate_resolution_rate": (
                    block.thresholds.min_corporate_resolution_rate
                ),
                "max_boundary_ratio": block.thresholds.max_boundary_ratio,
                "min_effect_size": block.thresholds.min_effect_size,
                "min_z": block.thresholds.min_z,
                "sweep_max_ratio": block.thresholds.sweep_max_ratio,
            },
            # 경계가 열려 층위·중심성을 산출하지 않았으면 False. 이게 없으면
            # `mean_supply_depth: null` 이 "깊이 0" 인지 "안 쟀다" 인지 구분되지 않는다.
            "topology_computed": block.topology_computed,
            "verdict": block.verdict.value,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
