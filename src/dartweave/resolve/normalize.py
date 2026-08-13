"""기업명 표기 정규화. 해소의 1단계."""
from __future__ import annotations

import re

_SUFFIXES = ("주식회사", "(주)", "㈜", "유한회사", "co.,ltd", "co.ltd", "ltd", "inc")
_WS = re.compile(r"\s+")


# ⚠️ RISK(side-effect): 접미사 제거가 반복 루프라 과도 제거 가능. 상호가 접미사로만 이뤄지면
# 빈 문자열이 되고, 서로 다른 두 회사가 같은 키로 뭉쳐 엉뚱한 corp_code 로 해소될 수 있다.
# 해소율 지표(AC-10)와 미해소 대기열로 감지하고, 오탐은 entity_alias 사전으로 보정할 것.
# — by main(3-checklist: shared state / 키 충돌)
def normalize_name(raw: str) -> str:
    text = _WS.sub("", str(raw or "")).lower()
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
