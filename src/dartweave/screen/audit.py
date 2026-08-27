"""감사의견 정규화 — 표기가 153종이라 규칙 없이 쓰면 라벨이 오염된다.

실측(상장사 3,983사·8,565건): `adt_opinion` 필드가 '적정'·'적정의견'·'적 정'·
'연결 : 적정\\n별도 : 적정' 처럼 제각각이고, 심한 경우 **감사보고서 전문 수천 자**가
그대로 들어와 있다.

⚠️ **판정 순서가 결정적이다.** 의견거절 본문에도 "적정" 이라는 글자가 들어 있어서,
   '적정' 을 먼저 보면 의견거절이 적정으로 뒤집힌다. 나쁜 쪽을 먼저 본다.

왜 이 라벨을 쓰나:
  주요사항보고 기반 라벨은 공시를 많이 하는 회사일수록 잡힐 확률이 높고, 그 편향이
  신호 검정 2호를 통째로 만들어냈다. 감사의견은 **모든 상장사가 매년 받으므로**
  탐지 확률이 회사마다 다르지 않다.
"""
from __future__ import annotations

from enum import Enum

# 나쁜 쪽부터. 순서를 바꾸면 의견거절이 적정으로 뒤집힌다.
_ORDER = (("의견거절", "DISCLAIMER"), ("부적정", "ADVERSE"), ("한정", "QUALIFIED"),
          ("적정", "CLEAN"))
GOING_CONCERN = "계속기업"


class Opinion(Enum):
    CLEAN = "적정"
    QUALIFIED = "한정"
    ADVERSE = "부적정"
    DISCLAIMER = "의견거절"
    UNKNOWN = "미상"

    @property
    def is_adverse(self) -> bool:
        """적정이 아닌 것. 미상은 나쁜 쪽으로도 좋은 쪽으로도 세지 않는다."""
        return self in (Opinion.QUALIFIED, Opinion.ADVERSE, Opinion.DISCLAIMER)


def normalize_opinion(raw: str) -> Opinion:
    text = str(raw or "").replace(" ", "")
    if not text:
        return Opinion.UNKNOWN
    for needle, name in _ORDER:
        if needle in text:
            return Opinion[name]
    return Opinion.UNKNOWN


def has_going_concern(emphasis: str) -> bool:
    """계속기업 불확실성 강조사항 — 감사인이 명시적으로 다는 경고. 부도보다 앞선다."""
    return GOING_CONCERN in str(emphasis or "").replace(" ", "")


# 기수 라벨 → 요청 연도 기준 오프셋. **여기가 연도 분리의 유일한 근거다.**
#
# ⚠️ `stlm_dt` 를 연도로 쓰면 안 된다. DART 는 한 번 호출에 당기·전기·전전기를
#    같이 주는데, 세 줄 **전부에 같은 결산일**(그 보고서의 결산일)을 붙인다.
#    실측 8,565건 중 8,313건이 2023-12-31 하나였다.
#
#    이걸 연도로 믿고 "2023년 감사의견" 을 고르면 2021·2022 가 딸려 들어온다.
#    그러면 3년 안에 한 번이라도 경고가 있었던 회사가 전부 걸려서, 회복한 회사까지
#    섞여 신호가 **희석**된다 — 계속기업 경고가 ×6.1 로 잰 게 실은 ×8.1 이었다.
_TERM_OFFSET = (("전전기", 2), ("전기", 1), ("당기", 0))


def term_year(term: str, requested_year: int) -> int | None:
    """기수 라벨에서 사업연도를 되살린다. `제38기(당기)` + 2023 → 2023.

    긴 것부터 본다 — "전기" 를 먼저 보면 "전전기" 가 전기로 읽힌다. 감사의견
    정규화에서 '적정' 을 먼저 보면 의견거절이 뒤집히던 것과 같은 함정이다.
    """
    text = str(term or "").replace(" ", "")
    for needle, back in _TERM_OFFSET:
        if needle in text:
            return requested_year - back
    return None


def rows_for_year(records: list[dict], year: int,
                  *, requested_year: int = 2023) -> list[dict]:
    """그 사업연도의 감사의견만. 저장된 `year` 를 우선하고 없으면 기수로 되살린다.

    `requested_year` 는 그 파일을 어떤 `--year` 로 받았는지다. 옛 수집본에는
    연도가 안 들어 있어서 이걸로 복원한다.
    """
    out = []
    for r in records or []:
        y = r.get("year")
        if y is None:
            y = term_year(r.get("term", ""), requested_year)
        if y == year:
            out.append(r)
    return out
