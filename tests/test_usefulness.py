"""유의한 것과 쓸 만한 것은 다른 말이다."""
import pytest

from dartweave.signal.usefulness import lift_ci, usefulness


def _pair(flagged_events, flagged_clean, unflagged_events, unflagged_clean):
    flags = [True] * (flagged_events + flagged_clean) + [False] * (unflagged_events + unflagged_clean)
    labels = ([True] * flagged_events + [False] * flagged_clean
              + [True] * unflagged_events + [False] * unflagged_clean)
    return flags, labels


def test_mismatched_lengths_are_rejected():
    """짝이 어긋나면 조용히 틀린 답이 나온다 — 막아야 한다."""
    with pytest.raises(ValueError):
        usefulness([True, False], [True])


def test_a_strong_lift_can_still_mean_most_flagged_are_fine():
    """실측 재현 — 결손금은 ×3.7 인데 걸린 기업의 94%는 아무 일도 없었다."""
    u = usefulness(*_pair(28, 435, 26, 1403))
    assert u.lift and u.lift > 2.0
    assert u.precision < 0.07              # 걸린 것 중 부실은 6%대
    assert 1 - u.precision > 0.9           # 94%는 무사
    assert "아무 일도 없었다" in u.explain()


def test_recall_shows_what_the_signal_misses():
    """부실의 절반을 놓치면 '부실을 잡아낸다' 고 말할 수 없다."""
    u = usefulness(*_pair(28, 435, 26, 1403))
    assert 0.4 < u.recall < 0.6


def test_a_signal_that_flags_everything_has_no_lift():
    u = usefulness(*_pair(50, 950, 0, 0))
    assert u.flagged_share == 1.0
    assert u.lift == pytest.approx(1.0)


def test_confidence_interval_brackets_the_point_estimate():
    """점추정 하나만 내면 확정된 값처럼 읽힌다."""
    flags, labels = _pair(28, 435, 26, 1403)
    u = usefulness(flags, labels)
    lo, hi = lift_ci(flags, labels, runs=400)
    assert lo < u.lift < hi and lo > 1.0


def test_empty_input_returns_none_rather_than_dividing_by_zero():
    assert lift_ci([], []) is None
    assert usefulness([], []).lift is None
