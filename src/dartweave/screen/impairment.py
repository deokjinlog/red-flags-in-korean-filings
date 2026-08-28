"""자본잠식까지 남은 분기 — **날짜가 아니라 구간으로만 말한다.**

왜 필요한가:
  "적자다" 는 상장사의 3분의 1에 붙는 이진 판정이라 그것만으로는 못 고른다.
  같은 적자라도 자본이 5년치 남은 회사와 1년치 남은 회사는 다른 회사다.
  실측으로도 갈린다 (T=2024, 스팩 제외 2,270사, 전체 부실률 2.42%):

    이미 잠식      50사  26.0%  x10.7
    1년 미만      101사   9.9%   x4.1
    1~2년         83사   7.2%   x3.0
    2~5년        171사   5.3%   x2.2
    5년 이상      431사   2.6%   x1.1
    흑자        1,434사   0.4%   x0.2

  단조다. 남은 분기가 길수록 부실률이 낮아진다.

⚠️ **그런데 이건 예측으로 쓰면 안 된다.** 직선 외삽이 실제로 얼마나 맞는지
   재봤더니 이랬다:

    2022 기준 "1년 안에 자본잠식 50% 도달" 예측 76사
      → 1년 뒤 실제 도달 11사 (14%)

   86%가 빗나간다. 증자 때문도 아니다 — 그 사이 증자한 51사의 도달률 16%,
   증자 안 한 25사가 12% 로 거의 같았다. **순손실이 그대로 유지된다는 가정
   자체가 안 맞는 것**이다(비용 절감·일회성 손실·자산 매각).

   그래서 "2027년 3월에 자본잠식됩니다" 라고 말하지 않는다. 말할 수 있는 건
   **어느 구간에 있는지와 그 구간의 실측 부실률**까지다. 이 저장소가 처음부터
   지켜온 규율과 같고, 여기서만 예외를 두면 그 규율이 무의미해진다.
"""

from __future__ import annotations

from dataclasses import dataclass

# 코스닥·코스피 상장규정의 관리종목 지정선. 우리가 고른 값이 아니다.
IMPAIRMENT_LINE = 0.5

# 구간별 실측 (T=20240630 · 관측 창 730일 · 스팩 제외 2,270사 · 전체 2.42%)
BANDS: tuple[tuple[float, float, str, int, float], ...] = (
    (0.0, 0.001, "이미 잠식", 50, 26.0),
    (0.001, 4.0, "1년 미만", 101, 9.9),
    (4.0, 8.0, "1~2년", 83, 7.2),
    (8.0, 20.0, "2~5년", 171, 5.3),
    (20.0, float("inf"), "5년 이상", 431, 2.6),
)
BASE_RATE = 2.42

# 이 외삽이 실제 자본잠식으로 이어진 비율. 화면에 같이 나가야 한다 —
# 안 붙이면 읽는 쪽이 이걸 날짜 예측으로 읽는다.
PROJECTION_HIT_RATE = 14
PROJECTION_NOTE = (
    f"이 계산은 **지금 손실 속도가 그대로 이어진다는 가정**입니다. "
    f"실제로 얼마나 맞는지 재봤더니, 1년 안에 도달한다고 나온 76사 중 "
    f"실제로 도달한 건 11사(**{PROJECTION_HIT_RATE}%**)였습니다. "
    f"날짜를 믿지 마시고 **어느 구간인지만** 보십시오."
)


@dataclass(frozen=True)
class Runway:
    quarters: float | None      # None = 흑자라 해당 없음
    band: str
    hit: int                    # 그 구간에 속했던 회사 수
    rate: float                 # 그 구간의 실측 부실률 (%)

    @property
    def ratio(self) -> float:
        return self.rate / BASE_RATE if BASE_RATE else 0.0

    def sentence(self) -> str:
        if self.quarters is None:
            return (f"흑자라 이 계산이 해당하지 않습니다 — "
                    f"흑자 기업의 이후 2년 부실률은 {self.rate:.1f}%입니다.")
        if self.band == "이미 잠식":
            return (f"자본잠식률이 이미 50%를 넘었습니다. 같은 상태였던 "
                    f"{self.hit}사 중 {self.rate:.1f}%가 이후 2년 안에 부실로 갔습니다 "
                    f"— 전체 평균의 {self.ratio:.1f}배.")
        return (f"지금 손실 속도면 자본잠식 50%까지 **{self.band}** 구간입니다. "
                f"같은 구간이었던 {self.hit}사 중 {self.rate:.1f}%가 이후 2년 안에 "
                f"부실로 갔습니다 — 전체 평균의 {self.ratio:.1f}배.")


def _band_of(q: float) -> tuple[str, int, float]:
    for lo, hi, name, hit, rate in BANDS:
        if lo <= q < hi:
            return name, hit, rate
    return BANDS[-1][2], BANDS[-1][3], BANDS[-1][4]


def runway(equity: float | None, capital: float | None,
           net_income: float | None) -> Runway | None:
    """자본잠식 50% 선까지 몇 분기. 모르면 None — 흑자와 구분한다.

    흑자는 "해당 없음"(quarters=None)이고, 값이 모자란 건 아예 None 이다.
    둘을 같이 두면 데이터가 없는 회사가 흑자로 보인다.
    """
    if equity is None or capital is None or net_income is None or capital <= 0:
        return None
    if equity <= IMPAIRMENT_LINE * capital:
        name, hit, rate = _band_of(0.0)
        return Runway(0.0, name, hit, rate)
    if net_income >= 0:
        return Runway(None, "해당 없음", 1434, 0.4)
    burn = -net_income / 4.0        # 분기 순손실
    q = (equity - IMPAIRMENT_LINE * capital) / burn
    name, hit, rate = _band_of(q)
    return Runway(q, name, hit, rate)
