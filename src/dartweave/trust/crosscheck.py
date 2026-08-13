"""정형 ↔ 정형 교차확인.

A사 「최대주주 현황」 과 B사 「타법인 출자현황」 은 같은 사실을 반대편에서 신고한 것이다.
둘이 어긋나면 **둘 다 법정 신고 항목이라 변명이 불가능하다** — 이게 1급 모순이다.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any

from dartweave.parse.relation import RelationEdge
from dartweave.trust.scope import Verdict, compare_scope, scope_key


class CrossResult(Enum):
    CONFIRMED = "confirmed"
    CONFLICT = "conflict"
    CHANGE = "change"
    SINGLE = "single"


@dataclass(frozen=True)
class CrossCheck:
    edge: RelationEdge
    status: CrossResult
    counterpart_rcept_no: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)


def _pair_key(holder_code: str, target_code: str) -> tuple[str, str]:
    return (holder_code, target_code)


def cross_check_structured(
    shareholder_edges: list[RelationEdge],
    investment_edges: list[RelationEdge],
    name_to_code: dict[str, str],
    code_to_name: dict[str, str],
) -> list[CrossCheck]:
    """최대주주 현황(보유자=이름) ↔ 타법인 출자현황(피출자=이름) 을 맞댄다."""
    # ⚠️ RISK(side-effect): 해소 안 된 이름은 ""가 되어 인덱스에서 조용히 빠진다.
    # 덕분에 엉뚱한 회사와 오매칭되진 않지만, 그 엣지는 CONFLICT 가 아니라 SINGLE 로 보고된다 —
    # 즉 "상대편 신고가 없다"와 "이름을 못 붙였다"가 결과에서 구분되지 않는다.
    # 해소율(AC-10)이 낮은 상태에서 SINGLE 비율을 신뢰도 근거로 쓰면 안 된다.
    # — by main(3-checklist: 실패가 정상 결과로 위장)
    index: dict[tuple[str, str], RelationEdge] = {}
    for inv in investment_edges:
        holder = inv.source_corp_code or ""
        target = name_to_code.get(inv.target_name or "", "")
        if holder and target:
            index[_pair_key(holder, target)] = inv

    # ⚠️ 「최대주주 현황」은 주식종류별로 행이 나뉘고(보통주/우선주),
    # 「타법인 출자현황」은 종류 통합으로 신고한다. 종류별 행 하나씩만 맞대면
    # 나머지 종류가 통째로 차이로 잡힌다.
    # 실측: 한화 -> 한화솔루션 62,420,460(보통) + 641,746(기타) = 63,062,206(통합)
    #       효성 -> 효성ITX     3,512,445 + 869,800 = 4,382,245
    # 따라서 (보유자, 대상, 스코프) 단위로 주식수를 합산한 뒤 비교한다.
    summed_qty: dict[tuple[str, str, tuple[str, str]], int] = {}
    for sh in shareholder_edges:
        holder = name_to_code.get(sh.source_name, "")
        target = sh.target_corp_code or ""
        if not holder or sh.share_qty is None:
            continue
        gk = (holder, target, scope_key(sh))
        summed_qty[gk] = summed_qty.get(gk, 0) + sh.share_qty

    results: list[CrossCheck] = []
    for sh in shareholder_edges:
        holder = name_to_code.get(sh.source_name, "")
        target = sh.target_corp_code or ""
        counterpart = index.get(_pair_key(holder, target)) if holder else None

        if counterpart is None:
            results.append(CrossCheck(sh, CrossResult.SINGLE))
            continue

        # 종류 합산본으로 비교한다 (원본 엣지는 종류별이라 그대로 쓰면 안 된다).
        group_qty = summed_qty.get((holder, target, scope_key(sh)))
        sh_for_compare = (
            replace(sh, share_qty=group_qty) if group_qty is not None else sh
        )
        verdict = compare_scope(sh_for_compare, counterpart)
        if verdict is Verdict.CHANGE:
            status = CrossResult.CHANGE
            detail: dict[str, Any] = {
                "from_fiscal_year": counterpart.fiscal_year,
                "to_fiscal_year": sh.fiscal_year,
            }
        elif verdict is Verdict.AGREE:
            status = CrossResult.CONFIRMED
            detail = {}
        else:
            status = CrossResult.CONFLICT
            gap = None
            if sh.share_pct is not None and counterpart.share_pct is not None:
                gap = round(abs(sh.share_pct - counterpart.share_pct), 6)
            qty_gap = None
            summed = sh_for_compare.share_qty
            if summed is not None and counterpart.share_qty is not None:
                qty_gap = abs(summed - counterpart.share_qty)
            detail = {
                "reported_by_target": sh.share_pct,
                "reported_by_holder": counterpart.share_pct,
                "gap": gap,
                # 주식수가 판정 근거다. 지분율 차이는 분모 차이일 수 있어
                # 참고값으로만 남긴다 (실측: 5.01% vs 4.4% = 같은 298,818,100주).
                "qty_by_target": sh_for_compare.share_qty,
                "qty_by_target_this_class": sh.share_qty,
                "qty_by_holder": counterpart.share_qty,
                "qty_gap": qty_gap,
            }
        results.append(
            CrossCheck(sh, status, counterpart.rcept_no, detail)
        )
    return results
