import pytest

from dartweave.structure.interpret import (
    HallucinationDetected,
    allowed_tokens,
    build_prompt,
    check_output,
    interpret,
)

# 군집 번호도 숫자다. 실제로는 allowed_tokens 가 payload 의 `"id":0` 에서 뽑아주지만,
# 픽스처를 손으로 쓸 때는 빠뜨리기 쉽다 — 빠뜨리면 정상 문장이 '지어낸 숫자' 로 걸린다.
NUMBERS = {"26.1", "11", "287", "0"}
KNOWN = frozenset({"삼성전자", "태영건설", "건설공제조합", "현대자동차"})


def test_prompt_forbids_inventing_content():
    p = build_prompt('{"clusters": []}')
    assert "수치에 없는" in p


def test_output_using_only_given_numbers_passes():
    ok, extra = check_output(
        "군집 0은 노드 11개, 외부 엣지 287개, 의존도 26.1이다.", NUMBERS, KNOWN
    )
    assert ok and extra == []


def test_ordinary_korean_prose_is_not_flagged():
    """한국어는 교착어라 조사·어미가 붙는다.

    실측: 순진한 고유명사 정규식은 "11개다" 에서 '개다' 를, "병목이다" 에서
    '병목이다' 를 고유명사로 잡았다. 불용어 목록으로는 끝이 없어서,
    **기업명 사전 대조**로 바꿨다.
    """
    ok, extra = check_output("군집 0은 노드 11개다.", NUMBERS, KNOWN)
    assert ok, extra


def test_invented_number_is_caught():
    ok, extra = check_output("의존도는 99.9이다.", NUMBERS, KNOWN)
    assert not ok and "99.9" in extra


def test_invented_company_name_is_caught():
    """AC-9 — 수치뿐 아니라 고유명사도 지어내면 안 된다."""
    ok, extra = check_output("삼성전자가 병목이다.", NUMBERS, KNOWN)
    assert not ok and "삼성전자" in extra


def test_company_name_present_in_the_input_is_allowed():
    """입력에 있던 회사는 당연히 언급해도 된다 — 검사 대상은 '지어낸 것' 뿐이다."""
    ok, extra = check_output("태영건설이 병목이다.", NUMBERS | {"태영건설"}, KNOWN)
    assert ok, extra


def test_parent_name_nested_in_an_allowed_subsidiary_is_not_flagged():
    """한국 기업명은 접두 중첩이 흔하다 — 포스코/포스코케미칼, 한화/한화솔루션.

    입력에 자회사만 있는데 부모 이름이 그 안에 포함돼 있다고 '지어냈다' 고
    걸면, 정상 문장이 반려된다. 실측으로 재현된 오탐이다.
    """
    known = frozenset({"포스코", "포스코케미칼"})
    ok, extra = check_output("포스코케미칼이 병목이다.", {"포스코케미칼"}, known)
    assert ok, extra


def test_parent_mentioned_on_its_own_is_still_flagged():
    """구제는 자회사 이름에 가려진 경우만. 부모를 따로 끌어오면 여전히 환각이다."""
    known = frozenset({"포스코", "포스코케미칼"})
    ok, extra = check_output("포스코가 병목이다.", {"포스코케미칼"}, known)
    assert not ok and "포스코" in extra


def test_allowed_tokens_extracts_numbers_and_names_from_payload():
    toks = allowed_tokens('{"clusters":[{"id":0,"nodes":11}],"lens":{"name":"supply"}}')
    assert "11" in toks and "supply" in toks


def test_interpret_runs_the_check_automatically():
    """AC-9 — 검사가 '자동으로' 수행돼야 한다.

    검사를 별도 함수로만 두면 호출을 잊는 순간 조용히 통과한다.
    문장을 얻는 유일한 경로가 검사를 통과하는 경로여야 한다.
    """
    payload = '{"clusters":[{"id":0,"nodes":11}]}'
    assert interpret(payload, lambda _: "군집 0은 노드 11개다.", KNOWN)

    with pytest.raises(HallucinationDetected) as ei:
        interpret(payload, lambda _: "삼성전자가 노드 99개로 병목이다.", KNOWN)
    assert "삼성전자" in str(ei.value)


def test_interpret_passes_the_built_prompt_to_the_model():
    seen: list[str] = []

    def fake(prompt: str) -> str:
        seen.append(prompt)
        return "노드 11개."

    interpret('{"clusters":[{"id":0,"nodes":11}]}', fake, KNOWN)
    assert "수치에 없는" in seen[0]
