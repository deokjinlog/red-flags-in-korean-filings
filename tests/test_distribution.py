"""분포 위치와 추세 — 한 회사만 봐서는 못 하는 것."""
from dartweave.screen.distribution import Trend, position, trend


def test_percentile_places_the_value_in_the_real_distribution():
    """임의 임계가 아니라 실측 분포 안의 위치다."""
    others = list(range(100))
    assert position(95, others).percentile == 95.0
    assert "상위 5%" in position(95, others).label


def test_direction_flips_for_metrics_where_low_is_bad():
    """안 뒤집으면 '영업손실이 큰데 좋은 쪽' 같은 소리가 나온다."""
    others = [float(x) for x in range(100)]
    worse = position(5.0, others, higher_is_worse=False)   # 영업이익 5 — 낮아서 나쁘다
    assert worse.percentile > 90


def test_small_sample_refuses_to_place():
    p = position(1.0, [0.0, 2.0, 3.0])
    assert "적다" in p.label


def test_missing_value_is_not_placed():
    assert position(None, [1.0, 2.0]) is None


def test_trend_translates_direction_to_meaning():
    """'줄어드는 중' 만 쓰면 지표에 따라 반대로 읽힌다 — 이익잉여금이 그렇다."""
    # 부채처럼 클수록 나쁜 지표
    assert Trend(["2021", "2024"], [100.0, 200.0]).arrow() == "악화 중"
    assert Trend(["2021", "2024"], [200.0, 100.0]).arrow() == "개선 중"
    # 이익잉여금처럼 작을수록 나쁜 지표 — 같은 하락이 반대 뜻이다
    low_bad = Trend(["2021", "2024"], [200.0, 100.0], higher_is_worse=False)
    assert low_bad.arrow() == "악화 중"
    assert Trend(["2021", "2024"], [100.0, 105.0]).arrow() == "거의 그대로"


def test_trend_needs_two_known_points():
    assert Trend(["2021", "2024"], [None, 100.0]).arrow() == "추세 판정 불가"
    assert Trend(["2021"], [1.0]).arrow() == "추세 판정 불가"


def test_missing_year_stays_none_not_zero():
    """0 으로 채우면 급감으로 읽힌다."""
    store = {"2023": {"A": {"부채총계": 100}}}
    t = trend(store, "A", "부채총계", ["2022", "2023"])
    assert t.values == [None, 100.0]
    assert "—" in t.as_row()
