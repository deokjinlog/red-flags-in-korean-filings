"""자금 캘린더 — 언제 얼마를 갚아야 하고, 지금 얼마가 있는가.

**왜 이게 따로 필요한가.** 우리 신호 8종은 전부 "이 계정이 음수냐" 는 상태
판정이다. 상태가 같아도 남은 시간이 다르면 다른 이야기다 — 적자 회사 둘 중
하나는 현금이 2 분기치고 다른 하나는 7 년치면, 같은 신호가 걸려도 같은 회사가
아니다.

여기는 예측이 아니라 **뺄셈**이다. 만기일은 발행 공시에 적혀 있고 보유 현금은
현금흐름표에 적혀 있다. 계수도 임계도 없다.

**과대추정 주의.** 우리는 발행 공시만 갖고 있고 *미상환 잔액* 은 모른다. 만기
전에 주식으로 전환됐거나 조기상환된 사채도 여전히 갚을 돈으로 세므로, 여기서
나오는 금액은 **실제 상환 부담의 위쪽 경계**다. 방향이 한쪽이라 신호를 실제보다
세게 만든다 — 검정에서 이걸 감안해서 읽어야 한다.

**만기는 늦은 쪽 경계이기도 하다.** 조기상환청구권(풋)이 붙은 사채는 만기보다
이르게 청구될 수 있는데, 청구 가능일은 발행 공시 본문의 산문이라 못 뽑는다.
그래서 풋 보유 여부를 따로 낸다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

_DOTTED = re.compile(r"^(\d{4})\s*[.\-/]\s*(\d{1,2})\s*[.\-/]\s*(\d{1,2})\.?$")
_KOREAN = re.compile(r"^(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일$")


def parse_maturity(text: str | None) -> date | None:
    """만기일. 두 형식이 섞여 있다 — "2027년 07월 30일" 과 "2029.04.12".

    실측으로 8,878 건 중 3,634 건만 한글 형식이다. 한쪽만 받으면 나머지를 조용히
    버리게 되고, 그러면 자금 캘린더가 절반만 보고 "갚을 게 없다" 고 말한다.
    """
    if not text:
        return None
    s = text.strip()
    for pattern in (_KOREAN, _DOTTED):
        m = pattern.match(s)
        if m:
            y, mo, d = (int(x) for x in m.groups())
            try:
                return date(y, mo, d)
            except ValueError:
                return None
    return None


@dataclass(frozen=True)
class Due:
    """기준일 이후 창 안에 만기가 오는 사채."""

    amount: float          # 발행액 합계 — 상환 부담의 위쪽 경계
    count: int
    with_put: int          # 그중 조기상환청구권이 붙은 건수

    @property
    def has_put(self) -> bool:
        return self.with_put > 0


def due_within(rows: list[dict], as_of: date, *, years: int = 2) -> Due:
    """`rows` 는 한 회사의 사채 발행 건들. 각각 amount·maturity·has_put 을 가진다.

    기준일 **이전에 발행**되고 기준일 **이후 `years` 안에 만기**가 오는 것만 센다.
    앞의 조건이 시점 분리다 — 기준일 뒤에 발행된 사채를 세면 미래를 훔쳐본다.
    """
    end = date(as_of.year + years, as_of.month, min(as_of.day, 28))
    amount = 0.0
    count = with_put = 0
    for r in rows:
        due = parse_maturity(r.get("maturity"))
        if due is None or not (as_of <= due <= end):
            continue
        amount += float(r.get("amount") or 0.0)
        count += 1
        if r.get("has_put"):
            with_put += 1
    return Due(amount=amount, count=count, with_put=with_put)
