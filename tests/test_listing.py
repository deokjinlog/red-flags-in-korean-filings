from dartweave.screen.listing import (
    NOT_COUNTED,
    OBSERVED,
    boxes,
    sales_note,
    summary,
)

FOUR_LOSSES = [-1.0, -2.0, -3.0, -4.0]


def test_thresholds_come_from_the_rulebook_not_from_us():
    """다른 신호는 우리가 임계를 골랐지만 여기는 상장규정에 박힌 숫자다."""
    assert "상장규정에 박힌 숫자" in summary(
        boxes(equity=40e8, capital=100e8, sales=None, op_by_year=FOUR_LOSSES))


def test_impairment_and_loss_streak_fire():
    b = {x.name: x for x in boxes(40e8, 100e8, None, FOUR_LOSSES)}
    assert b["자본잠식률 50% 이상"].hit is True     # (100-40)/100 = 60%
    assert b["자기자본 10억 미만"].hit is False      # 40억 > 10억
    assert b["4년 연속 영업손실"].hit is True


def test_missing_values_are_unknown_not_clean():
    """값이 없는 걸 '안 걸림' 으로 세면 데이터가 모자란 회사가 깨끗해 보인다."""
    b = {x.name: x for x in boxes(None, None, None, [None, -1.0, -1.0, -1.0])}
    assert all(x.hit is None for x in b.values())
    assert "판정 못 함" in summary(list(b.values()))


def test_loss_streak_needs_all_four_years():
    """3년치만 있으면 4년 연속인지 모른다."""
    b = {x.name: x for x in boxes(40e8, 100e8, None, [-1.0, -1.0, -1.0])}
    assert b["4년 연속 영업손실"].hit is None


def test_sales_is_reported_but_never_counted_as_a_box():
    """한 시점에서 ×1.1 로 신호가 아니고, 유예 여부를 가릴 수 없다."""
    names = {x.name for x in boxes(40e8, 100e8, 20e8, FOUR_LOSSES)}
    assert "매출액 30억 미만" not in names
    assert "매출액 30억 미만" in NOT_COUNTED and "매출액 30억 미만" not in OBSERVED
    note = sales_note(20e8, "21")
    assert "칸으로 세지 않습니다" in note and "기술성장특례 유예" in note
    # 업종이 아니면 유예 이야기를 붙이지 않는다 — 없는 근거를 만들지 않는다.
    assert "기술성장특례" not in sales_note(20e8, "26")
    assert sales_note(50e8, "21") == ""


def test_observed_numbers_carry_their_sample():
    """검정을 통과한 게 아니라 관측이다 — 표본이 문장에 같이 나가야 한다."""
    hit = next(x for x in boxes(40e8, 100e8, None, FOUR_LOSSES)
               if x.name == "자본잠식률 50% 이상")
    s = hit.sentence()
    assert "51사" in s and "25.5%" in s and "10.5배" in s
