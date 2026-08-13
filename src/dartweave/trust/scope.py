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
    """기준일이 있으면 **기준일만** 쓴다. 없을 때만 접수연도로 폴백.

    실데이터 반영: `fiscal_year` 는 사업연도가 아니라 **접수연도**다
    (FY2024 사업보고서의 rcept_no 는 2025 로 시작). 접수연도를 키에 섞으면
    같은 기준일의 정정공시가 다른 해에 접수됐다는 이유로 다른 버킷에 떨어져
    **진짜 불일치를 CHANGE 로 오분류하고 놓친다.**
    기준일이 곧 "언제 시점의 사실인가" 이므로 그것만으로 스코프를 정한다.
    """
    if edge.as_of:
        return ("", edge.as_of)
    return (edge.fiscal_year, edge.fiscal_year)


def compare_scope(a: RelationEdge, b: RelationEdge) -> Verdict:
    if scope_key(a) != scope_key(b):
        return Verdict.CHANGE

    # 주식수가 양쪽에 있으면 그걸로 판정한다 — 지분율보다 우선.
    # 실측: 삼성전자↔삼성물산은 같은 298,818,100주를 5.01%(보통주 기준)와
    # 4.4%(총발행주식 기준)로 신고한다. 지분율만 보면 분모 차이가 모순으로 둔갑하고,
    # 우선주를 발행한 거의 모든 기업에서 같은 오탐이 발생한다.
    if a.share_qty is not None and b.share_qty is not None:
        return Verdict.AGREE if a.share_qty == b.share_qty else Verdict.MISMATCH

    if a.share_pct is None or b.share_pct is None:
        return Verdict.AGREE if a.share_pct == b.share_pct else Verdict.MISMATCH
    if abs(a.share_pct - b.share_pct) <= RATIO_TOLERANCE:
        return Verdict.AGREE
    return Verdict.MISMATCH
