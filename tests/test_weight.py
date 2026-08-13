import pytest

from dartweave.trust.weight import (
    Coefficients,
    Grade,
    WeightInputs,
    evidence_weight,
    grade_of,
    summarize,
)


def _inp(**kw):
    base = dict(
        is_structured=True,
        confidence=None,
        cross_confirmed=False,
        mention_count=1,
        share_pct=None,
        observed_precision=None,
    )
    base.update(kw)
    return WeightInputs(**base)


def test_structured_edge_gets_full_source_weight():
    assert evidence_weight(_inp()) == pytest.approx(1.0)


def test_text_edge_uses_observed_precision_not_raw_confidence():
    """AC-4c — 모델이 주장한 confidence 가 산식에 직접 들어가면 안 된다."""
    w = evidence_weight(
        _inp(is_structured=False, confidence=0.95, observed_precision=0.70)
    )
    assert w == pytest.approx(0.70)


def test_text_edge_without_observed_precision_falls_back_conservatively():
    w = evidence_weight(_inp(is_structured=False, confidence=0.95))
    assert w == pytest.approx(Coefficients().unmeasured_text_weight)
    assert w < 0.95, "미측정 구간을 모델 주장값으로 채우면 안 됨"


def test_cross_confirmed_increases_weight():
    assert evidence_weight(_inp(cross_confirmed=True)) > evidence_weight(_inp())


def test_mention_count_is_capped():
    high = evidence_weight(_inp(mention_count=50))
    mid = evidence_weight(_inp(mention_count=6))
    assert high == pytest.approx(mid)


def test_share_pct_scales_quantitative_edges():
    assert evidence_weight(_inp(share_pct=50.0)) < evidence_weight(_inp(share_pct=100.0))


def test_grade_mapping():
    assert grade_of(_inp(cross_confirmed=True)) is Grade.T1
    assert grade_of(_inp()) is Grade.T2
    assert grade_of(_inp(is_structured=False)) is Grade.T3


def test_summarize_reports_distribution_and_conflicts():
    s = summarize(
        [_inp(cross_confirmed=True), _inp(), _inp(is_structured=False)],
        conflict_count=2,
    )
    assert s["T1"] == pytest.approx(1 / 3)
    assert s["T2"] == pytest.approx(1 / 3)
    assert s["T3"] == pytest.approx(1 / 3)
    assert s["conflicts"] == 2
