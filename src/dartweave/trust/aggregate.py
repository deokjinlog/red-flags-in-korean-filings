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

from dartweave.parse.structured_rel import is_aggregate_row, normalize_as_of, parse_qty, parse_ratio
from dartweave.trust.scope import qty_agrees


@dataclass(frozen=True)
class AggregateHolding:
    """최대주주 현황의 `계` 행 — 최대주주 본인 + 특별관계자 합산."""

    corp_code: str
    stock_knd: str
    as_of: str | None
    share_qty: int | None
    share_pct: float | None
    rcept_no: str


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
    CONFLICT = "conflict"
    NO_REPORT = "no_report"


@dataclass(frozen=True)
class AggCheck:
    aggregate: AggregateHolding
    status: AggResult
    counterpart: MajorReport | None = None
    detail: dict[str, Any] | None = None


def parse_holding_aggregates(payload: dict[str, Any]) -> list[AggregateHolding]:
    """`계` 행만 뽑는다. 개별 주주 행은 crosscheck 축이 가져간다."""
    out: list[AggregateHolding] = []
    for item in payload.get("list", []):
        if not is_aggregate_row(item):
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
        if not agg.as_of:
            results.append(AggCheck(agg, AggResult.NO_REPORT))
            continue
        counterpart = latest_report_before(by_corp.get(agg.corp_code, []), agg.as_of)
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

        status = AggResult.CONFIRMED if agrees else AggResult.CONFLICT
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
                },
            )
        )
    return results
