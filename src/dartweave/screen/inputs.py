"""검사에 넣을 입력을 한 곳에서 만든다.

왜 모으나:
  `check_company.py` 와 `ask.py` 가 같은 일을 각자 구현하고 있었고, **실제로 어긋났다** —
  재무 신호를 채택해놓고 `ask.py` 에는 물리지 않아서, "사도 되나" 라는 질문에
  **검정에서 떨어진 구조 정보만 답하고 통과한 재무는 빼놓는** 상태로 한동안 돌았다.

  검사가 늘 때마다 두 곳을 다 고쳐야 하면 언젠가 또 어긋난다. 여기 모아두면 한 곳만
  고치면 된다. `db/asof.py` 가 시점 조회를, `signal/labels.py` 가 부실 판정을 모은
  것과 같은 이유다.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

# 이자비용 우선순위 — 실제로 나간 현금이 가장 곧다. 금융원가에는 외환차손·파생상품
# 평가손실이 섞여 있어 이자보상배율을 실제보다 나쁘게 만든다.
INTEREST_KEYS = ("이자의지급", "이자비용", "금융원가")


@dataclass(frozen=True)
class Financials:
    """검사에 넣을 재무 입력. 값이 없으면 None — 모르는 걸 '양호' 로 세지 않는다."""

    retained_earnings: float | None = None
    operating_income: float | None = None
    net_income: float | None = None
    operating_cashflow: float | None = None
    interest_cost: float | None = None
    fiscal_year: str = ""


def _num(value) -> float | None:
    return float(value) if value is not None else None


def load_financials(
    corp_code: str,
    *,
    fin_path: str | Path = "data/fin_by_year.json",
    cash_path: str | Path = "data/cashflow_by_year.json",
) -> Financials:
    """가장 최근 사업연도의 재무를 읽어 온다.

    이익잉여금이 있는 가장 최근 연도를 기준연도로 삼는다 — 채택된 신호 중 가장 강한
    것이 결손금이라 그게 없으면 나머지를 실어도 반쪽이다.
    """
    fin = _read(fin_path)
    if not fin:
        return Financials()
    for year in sorted(fin, reverse=True):
        acc = fin[year].get(corp_code) or {}
        if "이익잉여금" not in acc:
            continue
        cash = (_read(cash_path).get(year, {}) or {}).get(corp_code) or {}
        interest = next((float(cash[k]) for k in INTEREST_KEYS if cash.get(k)), None)
        return Financials(
            retained_earnings=_num(acc.get("이익잉여금")),
            operating_income=_num(acc.get("영업이익")),
            net_income=_num(acc.get("당기순이익(손실)")),
            operating_cashflow=_num(cash.get("영업활동현금흐름")),
            interest_cost=interest,
            fiscal_year=year,
        )
    return Financials()


def _read(path: str | Path) -> dict:
    p = Path(path)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
