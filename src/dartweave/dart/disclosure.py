"""공시목록 → 원장 레코드."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DisclosureRow:
    rcept_no: str
    corp_code: str
    report_nm: str
    rcept_dt: str
    fiscal_year: str


def fiscal_year_of(rcept_no: str) -> str:
    """결정 5 — 접수번호 앞 4자리가 시점 스코프의 1차 키."""
    return rcept_no[:4]


def parse_disclosure_list(
    payload: dict[str, Any], *, name_contains: str | None = None
) -> list[DisclosureRow]:
    rows: list[DisclosureRow] = []
    for item in payload.get("list", []):
        report_nm = str(item.get("report_nm", "")).strip()
        if name_contains and name_contains not in report_nm:
            continue
        rcept_no = str(item.get("rcept_no", "")).strip()
        rows.append(
            DisclosureRow(
                rcept_no=rcept_no,
                corp_code=str(item.get("corp_code", "")).strip(),
                report_nm=report_nm,
                rcept_dt=str(item.get("rcept_dt", "")).strip(),
                fiscal_year=fiscal_year_of(rcept_no),
            )
        )
    return rows
