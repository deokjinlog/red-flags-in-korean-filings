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
