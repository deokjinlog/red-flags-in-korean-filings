from dartweave.parse.relation import EdgeType, RelationEdge, Source
from dartweave.trust.scope import Verdict, compare_scope


def _edge(rcept_no, as_of, pct):
    return RelationEdge(
        edge_type=EdgeType.MAJOR_SHAREHOLDER_OF,
        source_name="A",
        source_corp_code=None,
        target_name=None,
        target_corp_code="B",
        rcept_no=rcept_no,
        fiscal_year=rcept_no[:4],
        as_of=as_of,
        source=Source.STRUCTURED,
        share_pct=pct,
    )


def test_different_fiscal_year_is_change_not_mismatch():
    a = _edge("20240311000001", "20231231", 30.0)
    b = _edge("20250311000001", "20241231", 25.0)
    assert compare_scope(a, b) is Verdict.CHANGE


def test_same_scope_different_value_is_mismatch():
    a = _edge("20250311000001", "20241231", 30.0)
    b = _edge("20250315000009", "20241231", 25.0)
    assert compare_scope(a, b) is Verdict.MISMATCH


def test_same_scope_same_value_is_agreement():
    a = _edge("20250311000001", "20241231", 30.0)
    b = _edge("20250315000009", "20241231", 30.0)
    assert compare_scope(a, b) is Verdict.AGREE


def test_small_rounding_difference_is_agreement():
    a = _edge("20250311000001", "20241231", 30.00)
    b = _edge("20250315000009", "20241231", 30.004)
    assert compare_scope(a, b) is Verdict.AGREE


def test_same_fiscal_year_but_different_as_of_is_change():
    """같은 연도라도 기준일이 다르면 변동이다."""
    a = _edge("20250311000001", "20241231", 30.0)
    b = _edge("20250901000009", "20250630", 25.0)
    assert compare_scope(a, b) is Verdict.CHANGE


def test_missing_as_of_falls_back_to_fiscal_year():
    a = _edge("20250311000001", None, 30.0)
    b = _edge("20250315000009", None, 25.0)
    assert compare_scope(a, b) is Verdict.MISMATCH
