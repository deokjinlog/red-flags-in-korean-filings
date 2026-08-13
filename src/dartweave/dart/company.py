"""기업개황 API 응답 → 기업 레코드."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CompanyInfo:
    corp_code: str
    corp_name: str
    stock_code: str | None
    corp_cls: str | None
    induty_code: str | None
    est_dt: str | None
    acc_mt: str | None


def _clean(payload: dict[str, Any], key: str) -> str | None:
    value = str(payload.get(key, "")).strip()
    return value or None


def parse_company(corp_code: str, payload: dict[str, Any]) -> CompanyInfo:
    return CompanyInfo(
        corp_code=corp_code,
        corp_name=_clean(payload, "corp_name") or "",
        stock_code=_clean(payload, "stock_code"),
        corp_cls=_clean(payload, "corp_cls"),
        induty_code=_clean(payload, "induty_code"),
        est_dt=_clean(payload, "est_dt"),
        acc_mt=_clean(payload, "acc_mt"),
    )
