"""감사의견 정규화 — 표기 153종을 네 갈래로.

이 파일이 지키는 건 하나다: **판정 순서.** 의견거절 본문에도 '적정' 이 들어 있어서
순서를 틀리면 가장 나쁜 의견이 가장 좋은 의견으로 뒤집힌다.
"""
from dartweave.screen.audit import Opinion, has_going_concern, normalize_opinion


def test_plain_forms():
    for raw in ("적정", "적정의견", "적 정", "적  정", "적정함", "적정(공정)"):
        assert normalize_opinion(raw) is Opinion.CLEAN, raw


def test_combined_forms():
    assert normalize_opinion("연결 : 적정\n별도 : 적정") is Opinion.CLEAN
    assert normalize_opinion("- 연결 : 적정\n- 별도 : 적정") is Opinion.CLEAN


def test_adverse_forms():
    assert normalize_opinion("의견거절") is Opinion.DISCLAIMER
    assert normalize_opinion("의견거절(*1)") is Opinion.DISCLAIMER
    assert normalize_opinion("별도 :의견거절\n연결 :의견거절") is Opinion.DISCLAIMER
    assert normalize_opinion("한정의견") is Opinion.QUALIFIED
    assert normalize_opinion("감사범위제한으로 인한 한정") is Opinion.QUALIFIED
    assert normalize_opinion("부적정의견") is Opinion.ADVERSE


def test_full_report_text_is_not_flipped_by_the_word_clean():
    """실측 사고 방지 — 의견거절 본문 수천 자에 '적정' 이 여러 번 나온다.

    '적정' 을 먼저 보면 가장 나쁜 의견이 가장 좋은 의견으로 뒤집힌다.
    """
    body = ("우리는 별첨된 연결회사의 연결재무제표에 대하여 의견을 표명하지 않습니다. "
            "…취득금액 및 손상차손 금액의 적정성 등에 대하여… (연결감사보고서) "
            "우리의 의견으로는 …공정하게 표시하고 있습니다.(별도감사보고서) 의견거절")
    assert normalize_opinion(body) is Opinion.DISCLAIMER


def test_empty_is_unknown_not_clean():
    """실측 414건이 공란이다. 모르는 걸 '적정' 으로 세면 부실을 놓친다."""
    assert normalize_opinion("") is Opinion.UNKNOWN
    assert normalize_opinion(None) is Opinion.UNKNOWN
    assert not Opinion.UNKNOWN.is_adverse


def test_adverse_covers_three_kinds_only():
    assert [o for o in Opinion if o.is_adverse] == [
        Opinion.QUALIFIED, Opinion.ADVERSE, Opinion.DISCLAIMER]


def test_going_concern_emphasis():
    assert has_going_concern("계속기업 관련 중요한 불확실성")
    assert has_going_concern("계속 기업 존속능력에 의문")
    assert not has_going_concern("해당사항 없음")
    assert not has_going_concern("")
