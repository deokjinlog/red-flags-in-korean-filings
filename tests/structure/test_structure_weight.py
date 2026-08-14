from dartweave.structure.weight import EdgeEvidence, edge_weights
from dartweave.trust.weight import Coefficients


def _ev(**kw):
    base = dict(
        is_structured=True,
        cross_confirmed=False,
        mention_count=1,
        share_pct=None,
        observed_precision=None,
    )
    base.update(kw)
    return EdgeEvidence(**base)


def test_weights_come_from_layer0_inputs():
    ws = edge_weights([_ev(), _ev(cross_confirmed=True)])
    assert ws[1] > ws[0]


def test_coefficient_override_changes_weights():
    """민감도 스윕이 계수를 흔들 수 있어야 한다 (AC-8)."""
    base = edge_weights([_ev(cross_confirmed=True)])
    swept = edge_weights(
        [_ev(cross_confirmed=True)], Coefficients(cross_confirm_bonus=1.0)
    )
    assert base[0] != swept[0]


def test_weights_are_positive():
    """igraph 가중치는 양수여야 한다 — 0 이하면 Leiden 이 엣지를 무시한다."""
    ws = edge_weights([_ev(share_pct=0.0), _ev(is_structured=False)])
    assert all(w > 0 for w in ws)


def test_text_edge_never_uses_raw_confidence():
    """층0 AC-4c 를 그대로 승계 — EdgeEvidence 에 confidence 필드 자체가 없다."""
    assert "confidence" not in EdgeEvidence.__dataclass_fields__
