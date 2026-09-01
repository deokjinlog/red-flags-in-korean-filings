"""관리종목 지정 요건까지 몇 칸 — **판정선을 우리가 안 정한다.**

다른 신호는 전부 우리가 임계를 고르고 검정으로 정당화했다. 여기는 다르다 —
코스닥·코스피 상장규정에 숫자가 그대로 박혀 있고, 걸리면 관리종목이 된다.
"부채비율 200%가 위험한가" 같은 논쟁이 아예 없다.

⚠️ **이건 검정이 아니라 관측이다.** 요건에 걸리는 회사가 41~207사뿐이고 그중
   부실이 7~20건이라, 다른 신호에 걸었던 잣대(신호군 부실 20건 이상 × 규모·업종
   통제 7설정 × 기준시점 복수)를 통과하지 못한다. 그래서 "채택" 이라 하지 않고
   **표본을 밝히고 관측값만** 낸다.

실측 (스팩·영업정지 제외):

              T=2023 (2,260사·1.50%)      T=2024 (2,270사·2.42%)
  자본잠식 50%     57사 12.3% x8.2          51사 25.5% x10.5
  자기자본 10억     53사 13.2% x8.8          41사 17.1% x7.0
  4년 연속 영업손실 190사  4.2% x2.8         207사  9.7% x4.0
  매출 30억        58사  1.7% x1.1           53사  5.7% x2.3   <- 약하다

**매출 요건은 칸으로 세지 않는다.** 한 시점에서 x1.1 로 사실상 신호가 아니고,
안을 열어보면 의약품·연구개발이 26사(0.0% / 3.8%)로 낮다. 기술성장특례로 상장한
회사는 이 요건이 5년 유예되는데, DART 기업개황에 상장방식이 없어서 유예 여부를
직접 가릴 수가 없다. 가릴 수 없는 걸 세면 유예 중인 바이오가 전부 오경보가 된다.
그래서 참고로만 낸다.
"""

from __future__ import annotations

from dataclasses import dataclass

IMPAIRMENT = 0.5          # 자본잠식률 — 코스닥 상장규정
MIN_EQUITY = 10e8         # 자기자본 10억
MIN_SALES = 30e8          # 매출액 30억
LOSS_YEARS = 4            # 4사업연도 연속 영업손실

# (칸 이름, T=2023, T=2024) — 각각 (해당 수, 부실률 %, 배율)
OBSERVED: dict[str, tuple[tuple[int, float, float], tuple[int, float, float]]] = {
    "자본잠식률 50% 이상": ((57, 12.3, 8.2), (51, 25.5, 10.5)),
    "자기자본 10억 미만": ((53, 13.2, 8.8), (41, 17.1, 7.0)),
    "4년 연속 영업손실": ((190, 4.2, 2.8), (207, 9.7, 4.0)),
}
# 칸으로 세지 않는 것. 관측값은 남겨 둔다 — 왜 뺐는지 보여야 해서다.
NOT_COUNTED: dict[str, tuple[tuple[int, float, float], tuple[int, float, float]]] = {
    "매출액 30억 미만": ((58, 1.7, 1.1), (53, 5.7, 2.3)),
}

WHERE = {
    "자본잠식률 50% 이상": "연결 재무상태표 → (자본금 − 자본총계) ÷ 자본금",
    "자기자본 10억 미만": "연결 재무상태표 → 자본총계",
    "4년 연속 영업손실": "연결 포괄손익계산서 → 영업이익 (4개 사업연도)",
    "매출액 30억 미만": "연결 포괄손익계산서 → 매출액",
}


@dataclass(frozen=True)
class Box:
    name: str
    hit: bool | None          # None = 판정 못 함
    detail: str = ""

    @property
    def observed(self) -> tuple[int, float, float] | None:
        row = OBSERVED.get(self.name) or NOT_COUNTED.get(self.name)
        return row[1] if row else None       # 최신(T=2024) 관측

    def sentence(self) -> str:
        if self.hit is None:
            return f"{self.name} — **판정 못 함** (재무를 못 받았습니다)"
        if not self.hit:
            return f"{self.name} — 걸리지 않음"
        o = self.observed
        tail = (f" · 같은 칸이 걸렸던 {o[0]}사 중 {o[1]:.1f}%가 이후 2년 안에 "
                f"부실로 갔습니다(전체의 {o[2]:.1f}배)" if o else "")
        return f"**{self.name} — 걸림**{(' · ' + self.detail) if self.detail else ''}{tail}"


def _ratio(v: float | None, base: float | None) -> float | None:
    return None if v is None or not base or base <= 0 else v / base


def boxes(equity: float | None, capital: float | None, sales: float | None,
          op_by_year: list[float | None]) -> list[Box]:
    """규정 칸 판정. `op_by_year` 는 최근 것부터 4개다.

    모르면 None 이다 — 값이 없는 걸 "안 걸림" 으로 세면 데이터가 모자란 회사가
    깨끗해 보인다.
    """
    r = _ratio(None if capital is None or equity is None else capital - equity, capital)
    ops = op_by_year[:LOSS_YEARS]
    return [
        Box("자본잠식률 50% 이상", None if r is None else r >= IMPAIRMENT,
            "" if r is None else f"잠식률 {r * 100:.0f}%"),
        Box("자기자본 10억 미만", None if equity is None else equity < MIN_EQUITY,
            "" if equity is None else f"자본총계 {equity / 1e8:,.0f}억"),
        Box("4년 연속 영업손실",
            None if len(ops) < LOSS_YEARS or any(o is None for o in ops)
            else all(o < 0 for o in ops)),
    ]


def sales_note(sales: float | None, sector: str | None) -> str:
    """매출 요건은 칸이 아니라 참고다. 왜 참고인지를 같이 낸다."""
    if sales is None or sales >= MIN_SALES:
        return ""
    n, rate, ratio = NOT_COUNTED["매출액 30억 미만"][1]
    bio = sector in ("21", "70")      # 의약품 · 연구개발
    note = (f"매출액이 30억에 못 미칩니다({sales / 1e8:,.0f}억). **칸으로 세지 "
            f"않습니다** — 같은 조건 {n}사의 부실률이 {rate:.1f}%로 다른 칸보다 "
            f"약하고, 기준시점을 바꾸면 ×1.1까지 내려갑니다.")
    if bio:
        note += (" 게다가 이 회사는 의약품·연구개발 업종이라 **기술성장특례 유예** "
                 "대상일 수 있습니다. 유예 여부는 DART 기업개황에 상장방식이 없어 "
                 "여기서 가리지 못합니다 — 발행공시 「III. 투자위험요소」에서 "
                 "회사가 직접 밝힌 유예 종료 연도를 확인하십시오.")
    return note


def summary(found: list[Box]) -> str:
    hit = [b for b in found if b.hit is True]
    unknown = [b for b in found if b.hit is None]
    tail = f" · {len(unknown)}칸은 판정 못 함" if unknown else ""
    if not hit:
        return (f"관리종목 요건 {len(found)}칸 중 **걸린 칸 없음**{tail} — "
                f"판정선은 상장규정에 박힌 숫자이고 우리가 고른 값이 아닙니다.")
    return (f"관리종목 요건 {len(found)}칸 중 **{len(hit)}칸 걸림**{tail} — "
            f"{', '.join(b.name for b in hit)}. 판정선은 상장규정에 박힌 숫자입니다.")
