"""evidence_weight 파생 계산.

D5 — 값을 저장하지 않는다. 인자만 저장하고 여기서 계산한다.
정밀도 검수를 더 하면 observed_precision 이 좋아지고, 그때 전수 UPDATE 없이
모든 엣지 가중치가 갱신되어야 하기 때문이다.

계수는 임의값이므로 클래스로 분리한다 — 층1의 민감도 스윕이 이걸 흔든다.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


@dataclass(frozen=True)
class Coefficients:
    cross_confirm_bonus: float = 1.5
    mention_step: float = 0.1
    mention_cap: float = 1.5
    unmeasured_text_weight: float = 0.5


@dataclass(frozen=True)
class WeightInputs:
    is_structured: bool
    confidence: float | None
    cross_confirmed: bool
    mention_count: int
    share_pct: float | None
    observed_precision: float | None


class Grade(Enum):
    T1 = "T1"
    T2 = "T2"
    T3 = "T3"


def evidence_weight(x: WeightInputs, coef: Coefficients | None = None) -> float:
    c = coef or Coefficients()

    # 겹2-a 출처: 정형은 1.0, 본문은 '우리가 측정한' 정확도. 모델 주장값은 안 쓴다.
    if x.is_structured:
        w = 1.0
    elif x.observed_precision is not None:
        w = x.observed_precision
    else:
        w = c.unmeasured_text_weight

    # 겹2-b 교차확인
    if x.cross_confirmed:
        w *= c.cross_confirm_bonus

    # 겹2-c 반복 언급 (출처 주체 기준으로 이미 집계됨)
    w *= min(1 + c.mention_step * (max(x.mention_count, 1) - 1), c.mention_cap)

    # 겹3 정량속성: 값이 있을 때만. 없는 값을 추정하지 않는다.
    if x.share_pct is not None:
        w *= x.share_pct / 100

    return w


def grade_of(x: WeightInputs) -> Grade:
    if x.cross_confirmed:
        return Grade.T1
    return Grade.T2 if x.is_structured else Grade.T3


def summarize(inputs: list[WeightInputs], *, conflict_count: int) -> dict[str, float]:
    """AC-8 — 한 줄 요약: T1 x% · T2 y% · T3 z% · 충돌 n건."""
    total = len(inputs) or 1
    counts = {g: 0 for g in Grade}
    for x in inputs:
        counts[grade_of(x)] += 1
    result: dict[str, float] = {g.value: counts[g] / total for g in Grade}
    result["conflicts"] = conflict_count
    return result
