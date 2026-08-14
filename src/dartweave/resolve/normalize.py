"""기업명 표기 정규화. 해소의 1단계."""
from __future__ import annotations

import re

# 접두/접미로 붙는 법인격 표기. 실측으로 보강됨 —
# corpCode 정식명칭이 '사회복지법인삼성생명공익재단' 인데 공시는 '삼성생명공익재단' 으로 쓴다.
_SUFFIXES = (
    "주식회사", "유한회사", "유한책임회사", "합자회사", "합명회사",
    "사회복지법인", "학교법인", "의료법인", "재단법인", "사단법인", "공익법인",
    "co.,ltd", "co.ltd", "ltd", "inc",
)
# 순수 표기 기호라 **위치와 무관하게** 지운다.
# 실측: '삼성생명보험㈜\n(특별계정)' 은 ㈜ 가 중간에 있어 접두/접미 제거로는 안 지워졌다.
_CORP_MARKS = re.compile(r"㈜|\(주\)|\(株\)")
_WS = re.compile(r"\s+")


# ⚠️ RISK(side-effect): 접미사 제거가 반복 루프라 과도 제거 가능. 상호가 접미사로만 이뤄지면
# 빈 문자열이 되고, 서로 다른 두 회사가 같은 키로 뭉쳐 엉뚱한 corp_code 로 해소될 수 있다.
# 해소율 지표(AC-10)와 미해소 대기열로 감지하고, 오탐은 entity_alias 사전으로 보정할 것.
# — by main(3-checklist: shared state / 키 충돌)
def normalize_name(raw: str) -> str:
    text = _CORP_MARKS.sub("", str(raw or ""))
    text = _WS.sub("", text).lower()
    changed = True
    while changed:
        changed = False
        for suffix in _SUFFIXES:
            s = suffix.replace(" ", "").lower()
            if text.startswith(s):
                text, changed = text[len(s) :], True
            if text.endswith(s):
                text, changed = text[: -len(s)], True
    return text
