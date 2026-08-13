"""합산 지분 대조 — 「최대주주 현황」의 `계` 행 ↔ 「대량보유 상황보고」(5% 룰).

왜 별도 축인가:
  개별 주주 행끼리 맞대는 축(crosscheck.py)은 **법인 주주만** 대조가 된다.
  개인은 「타법인 출자현황」 신고 의무가 없기 때문이다. 실측에서 대조 가능 비율이
  5.6%(359건 중 20건)에 그친 이유가 이것이다.

  반면 「대량보유 상황보고」는 **개인도 보고 의무**가 있고, 그 보고값은
  본인+특별관계자 **합산**이다. 최대주주 현황의 `계` 행이 같은 개념의 합산이므로
  둘이 짝이 된다. 실측(삼성전자, 2024):
      계 행       1,198,033,154주 / 20.07%  (기준일 2024-12-31)
      대량보유보고 1,198,889,258주 / 20.08%  (접수일 2024-10-25)

시점 처리:
  대량보유보고는 **이벤트 기반**(접수일)이고 최대주주 현황은 **기간 기준**(기준일)이라
  날짜가 일치하는 법이 없다. 따라서 기준일 시점에 유효한 **직전 최신 보고**를 짝지운다.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from dartweave.parse.structured_rel import (
    is_aggregate_row,
    normalize_as_of,
    parse_qty,
    parse_ratio,
)
from dartweave.resolve.normalize import normalize_name
from dartweave.trust.scope import qty_agrees


@dataclass(frozen=True)
class AggregateHolding:
    """최대주주 현황의 `계` 행 — 최대주주 본인 + 특별관계자 합산.

    `members` 는 그 합계를 이루는 **특별관계자 명단**(정규화된 이름)이다.
    이게 없으면 국민연금이나 외국계 운용사처럼 무관한 보고자의 대량보유보고와 맞대게
    되어 전건 오탐이 된다 (실측: 삼성전자우 계행 0.12% vs 삼성물산 보고 20.07%).

    최대주주 **본인**이 아니라 명단 전체로 판정하는 이유: 대량보유보고의 대표보고자가
    최대 지분권자와 다를 수 있다. 실측으로 삼성전자의 최대주주 본인은 삼성생명(8.51%)
    이지만 대량보유 보고자는 삼성물산(5.01%)이다. 둘 다 같은 특별관계자 그룹이다.
    """

    corp_code: str
    stock_knd: str
    as_of: str | None
    share_qty: int | None
    share_pct: float | None
    rcept_no: str
    members: frozenset[str] = frozenset()
    # (이름, 주식수) — 차액을 어느 주주가 만들었는지 역산하는 데 쓴다.
    member_holdings: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True)
class MajorReport:
    """대량보유 상황보고 — 보고자 기준 합산(본인+특별관계자). 개인도 보고 주체가 된다."""

    corp_code: str
    reporter: str
    rcept_dt: str
    share_qty: int | None
    share_pct: float | None
    rcept_no: str


class AggResult(Enum):
    CONFIRMED = "confirmed"
    NEEDS_REVIEW = "needs_review"
    NO_REPORT = "no_report"


@dataclass(frozen=True)
class AggCheck:
    aggregate: AggregateHolding
    status: AggResult
    counterpart: MajorReport | None = None
    detail: dict[str, Any] | None = None


def group_members(payload: dict[str, Any]) -> frozenset[str]:
    """합계를 이루는 개별 주주(특별관계자) 이름 집합. 정규화해서 담는다."""
    return frozenset(
        normalize_name(str(item.get("nm", "")))
        for item in payload.get("list", [])
        if not is_aggregate_row(item) and str(item.get("nm", "")).strip()
    )


def member_holdings(payload: dict[str, Any], stock_knd: str = "보통주") -> tuple[tuple[str, int], ...]:
    """개별 주주의 (이름, 주식수). 차액 역산용."""
    out: list[tuple[str, int]] = []
    for item in payload.get("list", []):
        if is_aggregate_row(item):
            continue
        if str(item.get("stock_knd", "")).replace(" ", "") != stock_knd:
            continue
        nm = str(item.get("nm", "")).strip()
        qty = parse_qty(item.get("trmend_posesn_stock_co"))
        if nm and qty:
            out.append((nm, qty))
    return tuple(out)


def explain_gap(
    holdings: tuple[tuple[str, int], ...], gap: int, *, tolerance: int = 0
) -> list[tuple[str, ...]]:
    """차액을 만든 주주 조합을 역산한다.

    「대량보유 상황보고」는 **합계만** 주고 구성원 명단을 주지 않는다. 따라서
    "누가 한쪽에만 있는가" 는 직접 비교가 불가능하고, 차액과 일치하는 부분집합으로
    역산해야 한다. 실측(동진쎄미켐): 차액 1,880,000주 = 재단법인 동진장학연구재단 보유분.

    단건·2건 조합까지만 본다. 그 이상은 조합 폭발이고, 설명력도 급격히 떨어진다
    (여러 명을 임의로 묶으면 우연히 맞는 조합이 늘어나 설명이 아니라 억지가 된다).
    설명이 안 되면 빈 목록을 돌려준다 — **그 자체가 "사람이 봐야 한다" 는 신호다.**
    """
    if gap <= 0:
        return []
    found: list[tuple[str, ...]] = []
    for nm, qty in holdings:
        if abs(qty - gap) <= tolerance:
            found.append((nm,))
    if found:
        return found
    n = len(holdings)
    for i in range(n):
        for j in range(i + 1, n):
            if abs(holdings[i][1] + holdings[j][1] - gap) <= tolerance:
                found.append((holdings[i][0], holdings[j][0]))
    return found


def parse_holding_aggregates(payload: dict[str, Any]) -> list[AggregateHolding]:
    """`계` 행만 뽑는다. 개별 주주 행은 crosscheck 축이 가져간다.

    ⚠️ 보통주 계 행만 대상으로 한다. 「대량보유 상황보고」의 '주식등' 은 종류 구분 없이
    통합 집계라, 우선주 계 행과 맞대면 자릿수가 다른 비교가 되어 전건 오탐이 된다.
    """
    members = group_members(payload)
    holdings = member_holdings(payload)
    out: list[AggregateHolding] = []
    for item in payload.get("list", []):
        if not is_aggregate_row(item):
            continue
        if str(item.get("stock_knd", "")).replace(" ", "") != "보통주":
            continue
        pct = parse_ratio(item.get("trmend_posesn_stock_qota_rt"))
        qty = parse_qty(item.get("trmend_posesn_stock_co"))
        if pct is None and qty is None:
            continue  # '기타 / 계 / -' 같은 빈 요약 행
        out.append(
            AggregateHolding(
                corp_code=str(item.get("corp_code", "")).strip(),
                stock_knd=str(item.get("stock_knd", "")).strip(),
                as_of=normalize_as_of(item.get("stlm_dt")),
                share_qty=qty,
                share_pct=pct,
                rcept_no=str(item.get("rcept_no", "")).strip(),
                members=members,
                member_holdings=holdings,
            )
        )
    return out


def parse_major_reports(payload: dict[str, Any]) -> list[MajorReport]:
    """대량보유 상황보고.

    실측 필드: `repror`(보고자) · `stkqy`(보유주식등의 수) · `stkrt`(보유비율) ·
    `rcept_dt`(접수일). 기준일(`stlm_dt`)은 **없다** — 이벤트 기반 보고이기 때문.
    """
    out: list[MajorReport] = []
    for item in payload.get("list", []):
        out.append(
            MajorReport(
                corp_code=str(item.get("corp_code", "")).strip(),
                reporter=str(item.get("repror", "")).strip(),
                rcept_dt=normalize_as_of(item.get("rcept_dt")) or "",
                share_qty=parse_qty(item.get("stkqy")),
                share_pct=parse_ratio(item.get("stkrt")),
                rcept_no=str(item.get("rcept_no", "")).strip(),
            )
        )
    return out


def latest_report_before(
    reports: list[MajorReport], as_of: str
) -> MajorReport | None:
    """기준일 시점에 유효한 직전 최신 보고. 이벤트 기반이라 날짜가 일치할 수 없다."""
    prior = [r for r in reports if r.rcept_dt and r.rcept_dt <= as_of]
    if not prior:
        return None
    return max(prior, key=lambda r: (r.rcept_dt, r.rcept_no))


def _closest_mode(agg: AggregateHolding, rep: MajorReport) -> str:
    """보고값이 개별분에 가까운가, 합계에 가까운가 — 집계 범위 추정."""
    if rep.share_qty is None:
        return "unknown"
    own = next(
        (q for nm, q in agg.member_holdings if normalize_name(nm) == normalize_name(rep.reporter)),
        None,
    )
    d_total = abs(rep.share_qty - agg.share_qty) if agg.share_qty is not None else None
    d_own = abs(rep.share_qty - own) if own is not None else None
    if d_own is None and d_total is None:
        return "unknown"
    if d_own is None:
        return "group_total"
    if d_total is None or d_own < d_total:
        return "reporter_only"
    return "group_total"


def cross_check_aggregate(
    aggregates: list[AggregateHolding],
    reports: list[MajorReport],
    *,
    pct_tolerance: float = 1.0,
) -> list[AggCheck]:
    """합산 지분을 회사 신고(`계`)와 보고자 신고(대량보유)로 맞댄다.

    `pct_tolerance` 는 시차 흡수용이다. 대량보유보고는 5% 이상 변동 시에만 갱신되므로
    기준일과 최대 수개월 벌어질 수 있고, 그 사이 지분 변동은 정상이다.
    좁히면 정상 변동이 모순으로 쏟아지고, 넓히면 진짜 어긋남을 놓친다.
    """
    by_corp: dict[str, list[MajorReport]] = {}
    for r in reports:
        by_corp.setdefault(r.corp_code, []).append(r)

    results: list[AggCheck] = []
    for agg in aggregates:
        if not agg.as_of or not agg.members:
            results.append(AggCheck(agg, AggResult.NO_REPORT))
            continue
        # 같은 그룹의 보고만 짝지운다. 국민연금·외국계 운용사도 각자 5% 보고를 내므로
        # 보고자를 안 가리면 무관한 그룹끼리 비교하게 된다.
        same_group = [
            r
            for r in by_corp.get(agg.corp_code, [])
            if normalize_name(r.reporter) in agg.members
        ]
        counterpart = latest_report_before(same_group, agg.as_of)
        if counterpart is None:
            results.append(AggCheck(agg, AggResult.NO_REPORT))
            continue

        agrees = None
        if agg.share_qty is not None and counterpart.share_qty is not None:
            agrees = qty_agrees(agg.share_qty, counterpart.share_qty)
        if agrees is None and agg.share_pct is not None and counterpart.share_pct is not None:
            agrees = abs(agg.share_pct - counterpart.share_pct) <= pct_tolerance

        if agrees is None:
            results.append(AggCheck(agg, AggResult.NO_REPORT, counterpart))
            continue

        # 주식수가 어긋나도 지분율이 허용치 안이면 시차로 본다 (보고 갱신 지연).
        if not agrees and agg.share_pct is not None and counterpart.share_pct is not None:
            agrees = abs(agg.share_pct - counterpart.share_pct) <= pct_tolerance

        # ⚠️ 어긋남을 위반으로 단정하지 않는다. 실측으로 확인된 이유:
        # 「대량보유 상황보고」의 집계 범위가 케이스마다 다르다 — 어떤 보고는
        # 본인 단독, 어떤 보고는 본인+특별관계자 합산이며, 그 특별관계자 범위도
        # 「최대주주 현황」의 특수관계인(상법/공정거래법)과 근거 법령이 다르다.
        #   나혁휘: 개별 1,213,049 / 보고 1,393,049 / 계 14,849,438 — 어느 쪽과도 불일치
        #   이웅열: 개별 6,279,798 / 보고 7,081,539 / 계  6,583,039 — 계보다도 많음
        # 따라서 이 축은 **판정이 아니라 단서**를 낸다. 사람이 봐야 한다.
        status = AggResult.CONFIRMED if agrees else AggResult.NEEDS_REVIEW
        results.append(
            AggCheck(
                agg,
                status,
                counterpart,
                {
                    "reported_by_company": agg.share_qty,
                    "reported_by_holder": counterpart.share_qty,
                    "pct_by_company": agg.share_pct,
                    "pct_by_holder": counterpart.share_pct,
                    "as_of": agg.as_of,
                    "report_dt": counterpart.rcept_dt,
                    "reporter": counterpart.reporter,
                    # 실증 도출: 차이의 출처를 함께 내놔야 판정이 5초에 끝난다.
                    # 못 찾으면 빈 목록 — 그게 "사람이 봐야 한다" 는 신호다.
                    "gap_qty": (
                        abs(agg.share_qty - counterpart.share_qty)
                        if agg.share_qty is not None and counterpart.share_qty is not None
                        else None
                    ),
                    # 보고값이 개별분/계 중 어느 쪽에 가까운지 = 집계 범위 추정.
                    # 이게 있으면 사람이 "아 본인 단독 보고구나" 를 즉시 판단한다.
                    "closest_to": _closest_mode(agg, counterpart),
                    "gap_explained_by": (
                        explain_gap(
                            agg.member_holdings,
                            agg.share_qty - counterpart.share_qty,
                        )
                        if agg.share_qty is not None and counterpart.share_qty is not None
                        else []
                    ),
                },
            )
        )
    return results
