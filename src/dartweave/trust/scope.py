"""시점 스코프 판정.

결정 5 — 2023년 30% / 2024년 25% 는 불일치가 아니라 지분 매각이다.
정상 변화를 오류로 띄우면 1급 모순의 권위가 통째로 무너진다.
"""
from __future__ import annotations

from enum import Enum

from dartweave.parse.relation import RelationEdge

# ⚠️ RISK(side-effect): 이 값이 "무엇을 모순으로 볼지"를 직접 정한다. 좁히면 반올림 오탐이
# 쏟아지고 넓히면 진짜 불일치를 놓친다. 조용히 바꾸면 감사 결과 건수가 통째로 달라지므로,
# 변경 시 반드시 검출 건수 전후 비교를 남길 것.
# — by main(3-checklist: 하류 출력에 직결되는 임계값)
RATIO_TOLERANCE = 0.01  # 반올림 표기 차이 흡수


class Verdict(Enum):
    AGREE = "agree"
    MISMATCH = "mismatch"
    CHANGE = "change"


def scope_key(edge: RelationEdge) -> tuple[str, str]:
    """기준일이 있으면 그게 우선. 없으면 사업연도로 폴백."""
    return (edge.fiscal_year, edge.as_of or edge.fiscal_year)


def compare_scope(a: RelationEdge, b: RelationEdge) -> Verdict:
    if scope_key(a) != scope_key(b):
        return Verdict.CHANGE
    if a.share_pct is None or b.share_pct is None:
        return Verdict.AGREE if a.share_pct == b.share_pct else Verdict.MISMATCH
    if abs(a.share_pct - b.share_pct) <= RATIO_TOLERANCE:
        return Verdict.AGREE
    return Verdict.MISMATCH
