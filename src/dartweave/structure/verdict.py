"""결론 판정 — 세 상태가 동등하다.

이 층의 가장 큰 위험은 기술적 실패가 아니라 **데이터를 결론에 맞추는 것**이다.
하이라이트가 나와야 한다는 압력이 있으면 파라미터를 만질 유혹이 생긴다.
그래서 `결론 없음` 을 예외가 아닌 정식 반환값으로 두고, 스윕에 반려 권한을 준다.
"""
from __future__ import annotations

from enum import Enum

MIN_Z = 3.0
# 실측 접지: 무구조 ER 그래프의 효과크기가 ±0.02 까지 흔들린다 (igraph 1.0.0 측정).
# 임계를 0.02 에 두면 잡음이 통과한다. 실제 신호는 +0.1305 였으므로 0.05 는
# 잡음의 2.5배이면서 실측 신호의 1/2.6 — 양쪽에서 안전하다.
MIN_EFFECT = 0.05


class Verdict(Enum):
    ACCEPTED = "accepted"
    NO_CONCLUSION = "no_conclusion"
    PARAMETER_DEPENDENT = "parameter_dependent"


# ⚠️ RISK(breaking): 분기 **순서**가 판정을 바꾼다. 스윕 검사를 뒤로 미루면 특정
# 파라미터에서만 성립하는 우연이 채택된다. 또 `NO_CONCLUSION` 을 예외로 바꾸면
# AC-10 위반이고 호출부가 '결론 없음' 을 실패로 취급하게 된다.
# 알려진 한계: 불안정 + 약함이 겹치면 `PARAMETER_DEPENDENT` 만 나와 약하다는
# 사실이 가려진다. 그래서 판정은 항상 근거 블록의 원수치와 **함께** 보고할 것 —
# 판정 하나만 로그에 남기면 "파라미터만 잘 고르면 된다" 로 오독된다.
# — by main(3-checklist: 복잡한 분기 / 공개 반환 계약)
def decide(
    *, z: float, effect_size: float, sweep_holds: bool, has_outlier: bool
) -> Verdict:
    """판정 순서가 중요하다 — 불안정을 먼저 걸러야 우연을 채택하지 않는다."""
    if not sweep_holds:
        return Verdict.PARAMETER_DEPENDENT
    if z < MIN_Z or effect_size < MIN_EFFECT:
        return Verdict.NO_CONCLUSION
    if not has_outlier:
        return Verdict.NO_CONCLUSION
    return Verdict.ACCEPTED
