from dartweave.screen.impairment import (
    BASE_RATE,
    PROJECTION_HIT_RATE,
    PROJECTION_NOTE,
    runway,
)


def test_already_impaired_is_zero_not_a_projection():
    """이미 잠식된 회사에 '몇 분기 남았다' 를 말하면 안 된다."""
    r = runway(equity=40.0, capital=100.0, net_income=-10.0)
    assert r is not None and r.quarters == 0.0 and r.band == "이미 잠식"
    assert "이미" in r.sentence()


def test_profit_is_not_applicable_not_safe():
    """흑자는 '해당 없음' 이다. 안전 판정이 아니라 이 계산의 대상이 아니다."""
    r = runway(equity=100.0, capital=100.0, net_income=5.0)
    assert r is not None and r.quarters is None and r.band == "해당 없음"
    assert "해당하지 않습니다" in r.sentence()


def test_missing_data_is_none_not_profit():
    """값이 없는 걸 흑자로 세면 데이터 없는 회사가 안전해 보인다."""
    assert runway(None, 100.0, -10.0) is None
    assert runway(100.0, None, -10.0) is None
    assert runway(100.0, 100.0, None) is None
    assert runway(100.0, 0.0, -10.0) is None      # 자본금 0


def test_bands_are_measured_and_monotonic():
    """남은 분기가 길수록 부실률이 낮아야 한다 — 실측이 그랬다."""
    #  자본 100, 자본금 100 → 잠식선까지 50. 연 손실 200 이면 분기 50 → 1분기
    fast = runway(100.0, 100.0, -200.0)
    slow = runway(100.0, 100.0, -4.0)             # 분기 1 → 50분기
    assert fast.band == "1년 미만" and slow.band == "5년 이상"
    assert fast.rate > slow.rate
    assert fast.ratio > 1 and slow.ratio < 2


def test_projection_accuracy_travels_with_the_number():
    """86%가 빗나간다는 사실이 숫자와 같이 다니지 않으면 날짜 예측으로 읽힌다."""
    assert PROJECTION_HIT_RATE == 14
    assert "14%" in PROJECTION_NOTE and "구간" in PROJECTION_NOTE
    assert BASE_RATE == 2.42
