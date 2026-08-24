"""전환사채·신주인수권부사채 발행결정 파싱 — 조항까지 읽는다.

왜 횟수만으로는 부족한가:
  "최근 3년 사모 CB 2회" 같은 기준은 **몇 번 했는가**만 본다. 그런데 같은 한 번도
  조항에 따라 무게가 다르다 — 전환가능 물량이 발행주식의 26%인 건과 2%인 건이
  같을 수 없고, 리픽싱 하한이 액면가까지 열려 있는 건과 70%에서 멈추는 건이 다르다.

  DART 원문은 그걸 **코드로** 준다:

      STK_RT    전환가능주식수 ÷ 발행주식총수  = 오버행 비율 (실측 26.42)
      MIN_PRC   전환가액 조정 최저한도        = 리픽싱 하한
      OPT_FCT   옵션에 관한 사항 (본문)       = 풋/콜
      ISSU_MTH  사모 / 공모

  오버행 비율은 우리가 계산할 필요도 없이 제출사가 신고한 값이다.

옵션만 본문 문자열인 이유:
  풋/콜은 코드가 따로 없고 `OPT_FCT` 한 칸에 서술로 들어온다. 그래서 여기만
  문자열을 본다 — "조기상환청구권" / "Put Option" 은 풋, "매도청구권" / "Call
  Option" 은 콜이다. 이건 **분류지 추출이 아니라서** LLM 이 필요하지 않다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from dartweave.parse.body import coded_rows

_NUM = re.compile(r"[^\d.\-]")
_PUT = ("조기상환청구권", "putoption", "put option")
_CALL = ("매도청구권", "calloption", "call option", "콜옵션")


def _num(raw: str | None) -> float | None:
    if not raw or raw.strip() in {"-", ""}:
        return None
    try:
        return float(_NUM.sub("", raw))
    except ValueError:
        return None


@dataclass(frozen=True)
class BondIssue:
    amount: float | None          # 발행금액
    private: bool | None          # 사모인가
    overhang_pct: float | None    # 전환가능주식수 ÷ 발행주식총수 (%)
    exercise_price: float | None  # 전환가액
    refix_floor: float | None     # 리픽싱 하한
    has_put: bool                 # 조기상환청구권
    has_call: bool                # 매도청구권
    maturity: str | None          # 만기

    @property
    def refix_depth(self) -> float | None:
        """하한이 전환가의 몇 %까지 내려가는가. 낮을수록 희석 폭탄이다."""
        if self.refix_floor is None or not self.exercise_price:
            return None
        return self.refix_floor / self.exercise_price * 100.0


def parse_bond(xml: str) -> BondIssue | None:
    """발행결정 한 건. 코드가 하나도 없으면 None — 조용히 0 으로 채우지 않는다."""
    merged: dict[str, str] = {}
    for row in coded_rows(xml):
        for key, value in row.items():
            merged.setdefault(key, value)
    if "EXE_PRC" not in merged and "STK_CNT" not in merged:
        return None

    opt = (merged.get("OPT_FCT") or "").replace(" ", "").lower()
    method = merged.get("ISSU_MTH") or ""
    return BondIssue(
        amount=_num(merged.get("DNM_SUM")),
        private=("사모" in method) if method.strip() not in {"", "-"} else None,
        overhang_pct=_num(merged.get("STK_RT")),
        exercise_price=_num(merged.get("EXE_PRC")),
        refix_floor=_num(merged.get("MIN_PRC")),
        has_put=any(k.replace(" ", "") in opt for k in _PUT),
        has_call=any(k.replace(" ", "") in opt for k in _CALL),
        maturity=merged.get("EXP_DT"),
    )
