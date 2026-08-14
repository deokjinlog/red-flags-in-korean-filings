"""층0 인자 → igraph 엣지 가중치.

겹2(근거강도)·겹3(정량속성)은 층0 이 이미 정의했다. 여기서는 그걸 그대로 파생해
igraph 에 주입만 한다 — 층1이 별도 가중치 개념을 만들면 층0의 근거가 끊긴다.
"""
from __future__ import annotations

from dataclasses import dataclass

from dartweave.trust.weight import Coefficients, WeightInputs, evidence_weight

# ⚠️ RISK(side-effect): 하한이 없으면 가중치 0 엣지를 Leiden 이 사실상 끊어버려
# 그래프가 조용히 두 조각으로 갈린다(실측 확인). 대신 이 하한은 "측정해서 0" 과
# "그냥 아주 약함" 을 같은 값으로 뭉갠다 — `weight > 0` 을 "근거 있음" 으로 읽는
# 소비자가 생기면 오해한다. 지금은 그런 소비자가 없다.
# — by main(3-checklist: 공유 상태 / 경계값)
MIN_WEIGHT = 1e-6  # Leiden 이 엣지를 무시하지 않도록 하한을 둔다


@dataclass(frozen=True)
class EdgeEvidence:
    """가중치 산출에 필요한 층0 인자만. `confidence` 는 의도적으로 없다 (층0 AC-4c)."""

    is_structured: bool
    cross_confirmed: bool
    mention_count: int
    share_pct: float | None
    observed_precision: float | None


def edge_weights(
    evidence: list[EdgeEvidence], coef: Coefficients | None = None
) -> list[float]:
    out: list[float] = []
    for e in evidence:
        w = evidence_weight(
            WeightInputs(
                is_structured=e.is_structured,
                confidence=None,
                cross_confirmed=e.cross_confirmed,
                mention_count=e.mention_count,
                share_pct=e.share_pct,
                observed_precision=e.observed_precision,
            ),
            coef,
        )
        out.append(max(w, MIN_WEIGHT))
    return out
