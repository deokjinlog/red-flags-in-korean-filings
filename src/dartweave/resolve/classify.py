"""표기가 무엇을 가리키는가 — 해소율 분모를 정직하게 만들기 위한 분류.

왜 필요한가:
  corpCode 는 **국내 등록법인 명부**다. 공시에 등장하는 이름 중 상당수는 거기
  있을 수가 없고, 그런 걸 '매핑 실패' 로 세면 정상 상태가 불합격 처리된다.

  같은 오류를 두 번 겪었다.
  1차(개인 주주): 전체 해소율 29.7% 인데 대부분 홍라희·이재용 같은 개인이었다.
  2차(해외·집합체): 표본 15사 · 미해소 법인 201건을 분류했더니 해외법인 56.7% ·
     펀드/조합/특별계정 34.3% 로 **91%가 등재 대상이 아니었다.** 빼고 나면
     법인 해소율이 44.5% → 79.7% 가 된다.

판정 순서 (실측으로 두 번 뒤집힌 순서다):
  0. 해소되면 법인 — 정의상 확정. 호출부(Resolver)가 먼저 시도한다.
  1. 집합체 표지(투자조합·특별계정·사모투자합자회사…) → 등록 불가.
     법인 표지보다 먼저다. 안 그러면 '...투자유한회사' 가 법인으로 새어
     원리적으로 못 푸는 대상이 분모에 남는다.
  2. 인명 형태 → 자연인. 해외 판정보다 먼저다. 안 그러면 로마자 인명
     'MIRA SUH-HEE CHOI' 가 해외법인이 된다.
  3. 한글 없음 + 영문 있음 → 해외. 법인 표지보다 먼저다. 미해소의 56.7% 가
     Ltd/Corp 를 단 해외 자회사라, 표지를 먼저 보면 그 전부가 분모에 남는다.
  4. 법인 표지 → 법인 (미해소면 **진짜 문제**)
  5. 나머지 → 판정 불가. 모호한 걸 억지로 넣으면 진짜 실패가 지표에서 사라진다.
"""
from __future__ import annotations

import re
from enum import Enum

_CORPORATE_MARKERS = (
    "주식회사", "(주)", "㈜", "유한회사", "유한책임회사", "합자회사", "합명회사",
    "재단법인", "사단법인", "학교법인", "의료법인", "공익법인",
    "홀딩스", "지주", "조합", "공사", "공단", "협회", "재단", "기금",
    "은행", "보험", "증권", "캐피탈", "자산운용", "투자", "파트너스",
    "코퍼레이션", "인베스트",
    "co.,ltd", "co.ltd", "coltd", "ltd", "inc", "llc", "corp",
    "corporation", "limited", "holdings", "capital", "partners",
    "gmbh", "s.a.", "b.v.", "n.v.", "plc", "pte", "sdn", "bhd",
)

# 법인 등록 대상이 아닌 집합체. **corpCode 110,838건에 대조해서 골랐다** —
# 등재 수가 많은 낱말은 마커로 못 쓴다. 실측 등재 수:
#   조합 301 · 협동조합 265 · 사모 779 · 펀드 386 · 유동화 4,216 · 리츠 158 ·
#   투자회사 1,040 · 신탁 41   → 전부 탈락 (실제 등록법인을 오분류한다)
#   투자조합 5 · 특별계정 0 · 투자유한회사 0 · 사모투자합자회사 0 · 투자펀드 4 ·
#   벤처펀드 7 · 투자신탁 12 · 유한공사 32 · 기금 18   → 채택
# `공제조합` 은 등재 1건이 곧 건설공제조합 자신이라 뺐다.
# 공백·줄바꿈은 제거하고 대조한다 ('사모투자 합자회사', 이름 중간의 `\n`).
_UNREGISTRABLE_MARKERS = (
    "투자조합", "특별계정", "투자유한회사", "사모투자합자회사",
    "투자신탁", "투자펀드", "벤처펀드", "유한공사", "기금",
)
_WS = re.compile(r"\s+")

# 한글 인명은 3자가 압도적이다(김철수·홍라희·이재용). 2자·4자는 회사명과 구분이 안 된다
# — 삼성물산(4) · 고려아연(4) · 경방(2) · 한화(2) 가 전부 접미사 없는 법인명이다.
# **회사를 자연인으로 잘못 넣으면 진짜 매핑 실패가 지표에서 사라지므로**, 모호하면
# NATURAL 이 아니라 UNKNOWN 으로 보낸다. 게이트는 UNKNOWN 을 따로 센다.
_KOREAN_PERSON_CONFIDENT = re.compile(r"^[가-힣]{3}$")
# 공백을 끼워 쓴 표기('김 형 관')는 인명 관행이라 자수와 무관하게 인명으로 본다.
_KOREAN_SPACED_PERSON = re.compile(r"^[가-힣](\s+[가-힣]){1,4}$")
# 영문 인명: 2~4 토큰이 전부 알파벳 (예: MIRA SUH-HEE CHOI)
_LATIN_PERSON = re.compile(r"^[A-Za-z][A-Za-z.'\-]*(\s+[A-Za-z][A-Za-z.'\-]*){1,3}$")


class EntityKind(Enum):
    CORPORATE = "corporate"
    NATURAL = "natural"
    UNREGISTRABLE = "unregistrable"
    UNKNOWN = "unknown"


def _is_unregistrable(name: str) -> bool:
    """corpCode 에 **존재할 수 없는** 대상인가.

    corpCode 는 국내 등록법인 명부다. 해외 자회사·투자조합·보험 특별계정은 애초에
    등재 대상이 아니므로, 미해소가 정상이다 — 자연인과 같은 처지다.

    ⚠️ 이 판정은 **해소 실패 뒤에만** 의미가 있다. 호출부(Resolver)가 해소를 먼저
    시도하므로, 등재된 `사내근로복지기금` 류는 여기 오기 전에 CORPORATE 로 확정된다.
    """
    return any(k in _WS.sub("", name) for k in _UNREGISTRABLE_MARKERS)


def _is_foreign(name: str) -> bool:
    """한글이 **하나도 없고** 영문이 있으면 해외 표기.

    처음엔 "영문이 한글보다 많으면" 으로 했다가 `삼성SDI`(영문 3 vs 한글 2)가
    해외로 튀었다. 한글이 한 글자라도 있으면 국내 맥락으로 본다 — 국내 법인이
    영문 표기로만 등장하는 경우는 해소 단계가 먼저 잡는다.
    """
    latin = sum(c.isascii() and c.isalpha() for c in name)
    hangul = sum("가" <= c <= "힣" for c in name)
    return hangul == 0 and latin > 0


def classify_name(raw: str) -> EntityKind:
    """표기만으로 종류 추정. 해소 여부는 호출부가 우선 적용한다."""
    name = str(raw or "").strip()
    if not name:
        return EntityKind.UNKNOWN

    # 순서가 판정을 바꾼다. 실측으로 두 번 뒤집혔다:
    #  1. 집합체 판정이 법인 표지보다 뒤면 '...투자유한회사' 가 CORPORATE 로 새서
    #     원리적으로 못 푸는 대상이 분모에 남는다.
    #  2. 해외 판정이 인명보다 앞서면 'MIRA SUH-HEE CHOI'(로마자 인명)가
    #     해외법인이 된다.
    if _is_unregistrable(name):
        return EntityKind.UNREGISTRABLE

    if _KOREAN_SPACED_PERSON.fullmatch(name):
        return EntityKind.NATURAL
    if _KOREAN_PERSON_CONFIDENT.fullmatch(name.replace(" ", "")):
        return EntityKind.NATURAL
    if _LATIN_PERSON.fullmatch(name):
        return EntityKind.NATURAL

    # 해외 판정이 법인 표지보다 **먼저**다. 실측상 미해소 표기의 56.7% 가
    # 'Samsung SDI (Hong Kong) Ltd.' 처럼 Ltd/Corp 표지를 단 해외 자회사라,
    # 법인 표지를 먼저 보면 그 전부가 분모에 남는다.
    if _is_foreign(name):
        return EntityKind.UNREGISTRABLE

    lowered = name.replace(" ", "").lower()
    if any(m.replace(" ", "").lower() in lowered for m in _CORPORATE_MARKERS):
        return EntityKind.CORPORATE

    return EntityKind.UNKNOWN
