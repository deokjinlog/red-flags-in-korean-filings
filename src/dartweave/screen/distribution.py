"""분포 위치와 추세 — 한 회사만 봐서는 못 하는 것.

왜 이게 우리 몫인가:
  수기 리포트는 "이 숫자가 나쁜 건가" 에 답하려고 회사 둘을 나란히 놓는다. 그게
  최선인 이유는 한 회사만 읽어서는 **기준이 없기 때문**이다. 부채비율 749%가 나쁜
  건 알겠는데 300%는? 150%는?

  우리는 상장사 2,000여 곳의 같은 계정을 같은 해 기준으로 갖고 있다. 그래서
  **"상위 몇 %"** 를 낼 수 있다 — 임의 임계가 아니라 실측 분포 안의 위치다.
  이 저장소가 루브릭에서 이미 쓰던 방식을 재무로 옮긴 것뿐이다.

추세를 같이 내는 이유:
  단면 한 컷으로는 **개선 중인지 악화 중인지**를 못 가린다. 부채비율 749%가
  78% → 321% → 551% → 749% 로 온 것과 900% → 749% 로 온 것은 다른 이야기다.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Position:
    value: float
    percentile: float          # 낮을수록 좋은 지표 기준 — 0 이 가장 좋고 100 이 가장 나쁘다
    sample: int

    def describe(self, group: str = "상장사") -> str:
        """비교 대상을 이름으로 받는다.

        "상장사 중" 을 박아 두면 업종 내 비교를 같은 라벨로 낼 수 없다 — 전체
        분포와 업종 분포는 다른 이야기고, 어느 쪽인지 안 밝히면 읽는 쪽이 섞는다.
        """
        top = 100.0 - self.percentile
        if top <= 5:
            return f"{group} 중 **상위 {top:.0f}%** (나쁜 쪽)"
        if top <= 25:
            return f"{group} 중 상위 {top:.0f}%"
        if self.percentile <= 25:
            return f"{group} 중 하위 {self.percentile:.0f}% (좋은 쪽)"
        return f"{group} 중 상위 {top:.0f}% — 중간대"

    @property
    def label(self) -> str:
        return self.describe()


MIN_SAMPLE = 50
"""전체 분포에서 위치를 말하려면 이만큼은 있어야 한다."""


def position(value: float | None, others: list[float], *,
             higher_is_worse: bool = True,
             min_sample: int = MIN_SAMPLE) -> Position | None:
    """실측 분포 안의 위치. 임의 임계를 쓰지 않는다.

    `higher_is_worse` 가 False 면(예: 영업이익·현금) 낮을수록 나쁜 지표라 뒤집는다.
    뒤집지 않으면 "영업손실이 큰데 하위 5%(좋은 쪽)" 같은 소리가 나온다.

    `min_sample` 은 업종 내 비교처럼 표본이 작아지는 곳에서 낮춰 쓴다. 숫자 몇 개로
    만든 백분위는 위치가 아니라 잡음이라, 하한 밑이면 아예 내지 않는다.
    """
    if value is None or len(others) < max(2, min_sample):
        return None
    ordered = sorted(others)
    below = sum(1 for v in ordered if v < value)
    pct = below / len(ordered) * 100.0
    if not higher_is_worse:
        pct = 100.0 - pct
    return Position(value=value, percentile=pct, sample=len(ordered))


@dataclass(frozen=True)
class Trend:
    years: list[str]
    values: list[float | None]

    higher_is_worse: bool = True

    def arrow(self) -> str:
        """**좋아지는지 나빠지는지**로 말한다.

        "줄어드는 중" 만 쓰면 지표에 따라 반대로 읽힌다 — 이익잉여금이 줄어드는 건
        나쁜 건데 좋게 읽힌다. 방향을 지표 의미에 맞춰 번역한다.

        몇 % 나아졌다는 건 안 쓴다. 회계 변경에도 흔들리는 숫자다.
        """
        known = [v for v in self.values if v is not None]
        if len(known) < 2:
            return "추세 판정 불가"
        first, last = known[0], known[-1]
        if first == 0:
            return "추세 판정 불가"
        change = (last - first) / abs(first)
        if abs(change) <= 0.15:
            return "거의 그대로"
        rising = change > 0
        worse = rising if self.higher_is_worse else not rising
        return "악화 중" if worse else "개선 중"

    def as_row(self, unit: float = 1e8) -> str:
        cells = []
        for y, v in zip(self.years, self.values):
            cells.append(f"{y[2:]} {'—' if v is None else f'{v / unit:,.0f}'}")
        return " · ".join(cells)


def trend(by_year: dict, corp_code: str, account: str, years: list[str],
          *, higher_is_worse: bool = True) -> Trend:
    """연도별 계정값. 없는 해는 None 으로 둔다 — 0 으로 채우면 급감으로 읽힌다."""
    out: list[float | None] = []
    for y in years:
        raw = (by_year.get(y, {}).get(corp_code) or {}).get(account)
        out.append(float(raw) if raw is not None else None)
    return Trend(years=years, values=out, higher_is_worse=higher_is_worse)
