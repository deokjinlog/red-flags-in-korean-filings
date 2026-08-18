"""LLM 해석 — 숫자를 만들지 않고 문장으로 옮기기만 한다.

환각을 사후에 잡는 게 아니라 **구조적으로 발생 못 하게** 한다. 계산은 엔진이 하고
LLM 은 이미 나온 표만 본다. 그리고 출력이 입력 토큰 집합을 벗어났는지 기계 검사한다.

모듈을 (프롬프트 생성 + 출력 검사) 로 쪼갠 이유: 모델 호출 없이 검사 함수만
단위 테스트하기 위해서다. 모델 응답 품질은 테스트 대상이 아니다.

**검사 방식이 두 갈래인 이유.** 숫자는 모호성이 없어 집합 대조로 끝난다. 그런데
고유명사를 정규식으로 잡으려던 첫 설계는 한국어에서 무너졌다 — 교착어라 조사·어미가
붙어서 "11개다" 의 '개다', "병목이다" 의 '병목이다' 가 고유명사로 잡혔다(실측).
불용어 목록을 늘리는 건 끝이 없다. 대신 **우리가 이미 가진 corpCode 실명 목록**과
대조한다: 사전에 있는 회사 이름이 출력에 있는데 입력에 없었다면, 그건 지어낸 것이다.
일반 산문 낱말은 사전에 없으므로 오탐이 나지 않는다(실측 확인).

**이 검사가 보장하는 범위를 정확히 말하면**: "실재하는 회사인데 입력에 없던 것" 을
잡는다. 사전에 아예 없는 완전 허구의 이름은 못 잡는다. 그래도 이게 유효한 이유는
현실적인 실패 모드가 **모델이 학습에서 기억한 진짜 회사를 끌어오는 것**이기 때문이다.
없는 회사를 창작하는 쪽은 프롬프트 금지로 막고, 남는 위험은 여기 적어 둔다.
"""
from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable

_NUMBER = re.compile(r"\d+(?:\.\d+)?")

# 2자 회사명은 일반어와 겹친다 — '대상'·'경방' 처럼. 3자 이상만 대조해서
# 오탐을 막는다. 대신 2자 회사명은 검출 사각지대로 남는다(알려진 한계).
MIN_ENTITY_LEN = 3

PROMPT_TEMPLATE = """아래는 그래프 분석 결과다. 이 수치만으로 설명하라.
수치에 없는 내용은 절대 추가하지 마라. 회사 이름을 지어내지 마라.

{payload}
"""


def allowed_tokens(payload_json: str) -> set[str]:
    """입력에 등장하는 숫자·이름. 출력은 이 안에서만 놀아야 한다."""
    toks: set[str] = set()

    def walk(node: object) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                toks.add(str(k))
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
        elif node is not None:
            toks.add(str(node))

    walk(json.loads(payload_json))

    # 문자열 **안에 박힌 숫자**도 허용한다. 근거가 "매개중심성 3위" 로 통째로 들어오면
    # 모델은 자연히 "3위" 라고 풀어 쓰는데, 낱개 '3' 이 없어 정상 문장이 반려됐다(실측).
    # 막는 방향으로 틀린 거라 안전하긴 하지만, 이대로면 생성 단계를 못 붙인다.
    for t in list(toks):
        toks.update(_NUMBER.findall(t))

    # 소수 표기 흔들림만 흡수한다 ("26.10" → "26.1"). **정수는 건드리지 않는다** —
    # 실측 결함: 400 을 rstrip("0") 하면 4 가 되고, 4 가 허용 토큰에 있어서
    # "부채비율 400%" 같은 완전한 환각이 통과했다.
    for t in [x for x in toks if _NUMBER.fullmatch(x) and "." in x]:
        toks.add(t.rstrip("0").rstrip("."))
    return toks


def build_prompt(payload_json: str) -> str:
    return PROMPT_TEMPLATE.format(payload=payload_json)


# ⚠️ RISK(side-effect): `known_entities` 가 비면 기업명 검사가 통째로 무력화되는데
# 예외 없이 통과한다. 빈 목록은 "통과" 가 아니라 "검사 안 함" 이다 — 호출부는
# 해소 사전의 키를 항상 넘길 것.
# 사각지대 둘: (1) 2자 회사명(`대상`·`경방`)은 일반어와 겹쳐 제외된다, (2) 사전에
# 없는 완전 허구의 이름은 원리적으로 못 잡는다. 둘 다 모듈 docstring 에 적혀 있다.
# — by main(3-checklist: 경계값 / 조용한 무력화)
def check_output(
    text: str, allowed: set[str], known_entities: Iterable[str]
) -> tuple[bool, list[str]]:
    """출력에 입력 밖 숫자·기업명이 있으면 실패.

    `known_entities` 는 corpCode 실명 목록 (해소 사전의 키). 이게 있어야
    "지어낸 회사" 와 "그냥 한국어 낱말" 을 구분할 수 있다.
    """
    extra: list[str] = []
    for m in _NUMBER.findall(text):
        norm = m.rstrip("0").rstrip(".") if "." in m else m
        if m not in allowed and norm not in allowed:
            extra.append(m)
    for name in known_entities:
        if len(name) < MIN_ENTITY_LEN or name not in text or name in allowed:
            continue
        # 접두 중첩 구제: 허용된 더 긴 이름이 본문에 있고 그 안에 이 이름이
        # 들어 있으면, 부모 회사가 '등장한' 게 아니라 자회사 이름의 일부일 뿐이다.
        # 실측 오탐: 입력에 포스코케미칼만 있는데 '포스코' 가 지어낸 이름으로 걸렸다.
        if any(len(a) > len(name) and name in a and a in text for a in allowed):
            continue
        extra.append(name)
    return (not extra), extra


class HallucinationDetected(RuntimeError):
    """모델이 입력 수치 밖의 숫자·기업명을 만들어냈다."""


def interpret(
    payload_json: str,
    call_model: Callable[[str], str],
    known_entities: Iterable[str],
) -> str:
    """AC-9 — 해석문을 얻는 **유일한 경로**. 검사를 건너뛸 수 없다.

    `check_output` 을 따로 부르게 두면 호출을 잊는 순간 환각이 조용히 통과한다.
    모델 호출은 주입받는다 — 이 층은 어떤 모델을 쓰는지 알 필요가 없고,
    그 덕분에 검사 로직을 모델 없이 단위 테스트할 수 있다.
    """
    text = call_model(build_prompt(payload_json))
    ok, extra = check_output(text, allowed_tokens(payload_json), known_entities)
    if not ok:
        raise HallucinationDetected(
            f"입력에 없는 토큰 {len(extra)}건: {', '.join(extra[:10])}"
        )
    return text
