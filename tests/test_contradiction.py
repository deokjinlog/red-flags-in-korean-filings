from dartweave.parse.relation import EdgeType, RelationEdge, Source
from dartweave.trust.contradiction import detect_grade_a


def _sh(holder, target, pct, rcept="20250311000001", as_of="20241231"):
    return RelationEdge(
        edge_type=EdgeType.MAJOR_SHAREHOLDER_OF,
        source_name=holder,
        source_corp_code=None,
        target_name=None,
        target_corp_code=target,
        rcept_no=rcept,
        fiscal_year=rcept[:4],
        as_of=as_of,
        source=Source.STRUCTURED,
        share_pct=pct,
    )


def test_detects_sum_over_100():
    findings = detect_grade_a([_sh("A", "X", 51.0), _sh("B", "X", 37.3), _sh("C", "X", 30.0)])
    assert len(findings) == 1
    assert findings[0].detail["total"] == 118.3
    assert findings[0].grade == "A"


def test_normal_sum_is_not_flagged():
    assert detect_grade_a([_sh("A", "X", 51.0), _sh("B", "X", 30.0)]) == []


def test_tolerance_absorbs_rounding():
    """100.3 은 반올림 누적일 수 있다. 이걸 띄우면 오탐이 쏟아진다."""
    assert detect_grade_a([_sh("A", "X", 50.2), _sh("B", "X", 50.1)]) == []


def test_different_scopes_are_summed_separately():
    """다른 기준일끼리 합치면 정상 기업이 전부 위반으로 나온다."""
    edges = [
        _sh("A", "X", 60.0, rcept="20240311000001", as_of="20231231"),
        _sh("B", "X", 60.0, rcept="20250311000001", as_of="20241231"),
    ]
    assert detect_grade_a(edges) == []


def test_missing_share_pct_is_ignored_not_zero():
    findings = detect_grade_a([_sh("A", "X", None), _sh("B", "X", 99.0)])
    assert findings == []
