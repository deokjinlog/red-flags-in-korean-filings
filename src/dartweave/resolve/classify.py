"""주주 이름이 법인인가 자연인인가.

왜 필요한가:
  「최대주주 현황」의 주주 목록에는 법인과 개인이 섞여 있다. 개인은 `corp_code` 가
  애초에 없으므로 **미해소가 정상**인데, 해소율을 통째로 세면 그게 실패로 잡힌다.
  실측(삼성전자·SK하이닉스): 전체 해소율 29.7% — 홍라희·이재용 같은 개인 주주 때문이며
  법인만 보면 훨씬 높다. 층1 품질 게이트(AC-12)가 이 값을 그대로 임계로 쓰면
  **정상 상태를 불합격 처리한다.**

판정 순서:
  1. 해소되면 법인 (정의상 확정 — corpCode 에 등재된 것)
  2. 미해소면 표기로 추정: 법인 표지가 있으면 법인(미해소 = 진짜 문제),
     짧은 인명 형태면 자연인(미해소 = 정상), 나머지는 판정 불가
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
    UNKNOWN = "unknown"


def classify_name(raw: str) -> EntityKind:
    """표기만으로 법인/자연인 추정. 해소 여부는 호출부가 우선 적용한다."""
    name = str(raw or "").strip()
    if not name:
        return EntityKind.UNKNOWN

    lowered = name.replace(" ", "").lower()
    if any(m.replace(" ", "").lower() in lowered for m in _CORPORATE_MARKERS):
        return EntityKind.CORPORATE

    if _KOREAN_SPACED_PERSON.fullmatch(name):
        return EntityKind.NATURAL
    if _KOREAN_PERSON_CONFIDENT.fullmatch(name.replace(" ", "")):
        return EntityKind.NATURAL
    if _LATIN_PERSON.fullmatch(name):
        return EntityKind.NATURAL

    return EntityKind.UNKNOWN
