from dartweave.parse.relation import EdgeType, RelationEdge, Source
from dartweave.trust.crosscheck import CrossResult, cross_check_structured


def _sh(holder_name, target, pct, rcept="20250311000001", as_of="20241231"):
    return RelationEdge(
        edge_type=EdgeType.MAJOR_SHAREHOLDER_OF,
        source_name=holder_name,
        source_corp_code=None,
        target_name=None,
        target_corp_code=target,
        rcept_no=rcept,
        fiscal_year=rcept[:4],
        as_of=as_of,
        source=Source.STRUCTURED,
        share_pct=pct,
        reporter_corp_code=target,
    )


def _inv(holder, target_name, pct, rcept="20250311000002", as_of="20241231"):
    return RelationEdge(
        edge_type=EdgeType.INVESTS_IN,
        source_name="",
        source_corp_code=holder,
        target_name=target_name,
        target_corp_code=None,
        rcept_no=rcept,
        fiscal_year=rcept[:4],
        as_of=as_of,
        source=Source.STRUCTURED,
        share_pct=pct,
        reporter_corp_code=holder,
    )


NAME_TO_CODE = {"삼성생명보험": "001", "에이사": "002"}
CODE_TO_NAME = {"001": "삼성생명보험", "002": "에이사"}


def test_matching_pair_is_confirmed():
    res = cross_check_structured(
        [_sh("삼성생명보험", "002", 30.0)],
        [_inv("001", "에이사", 30.0)],
        NAME_TO_CODE,
        CODE_TO_NAME,
    )
    assert res[0].status is CrossResult.CONFIRMED


def test_value_gap_in_same_scope_is_conflict():
    res = cross_check_structured(
        [_sh("삼성생명보험", "002", 30.0)],
        [_inv("001", "에이사", 25.0)],
        NAME_TO_CODE,
        CODE_TO_NAME,
    )
    assert res[0].status is CrossResult.CONFLICT
    assert res[0].detail["gap"] == 5.0


def test_different_scope_is_change_not_conflict():
    res = cross_check_structured(
        [_sh("삼성생명보험", "002", 30.0, rcept="20240311000001", as_of="20231231")],
        [_inv("001", "에이사", 25.0)],
        NAME_TO_CODE,
        CODE_TO_NAME,
    )
    assert res[0].status is CrossResult.CHANGE


def test_no_counterpart_is_single_source():
    res = cross_check_structured(
        [_sh("삼성생명보험", "002", 30.0)], [], NAME_TO_CODE, CODE_TO_NAME
    )
    assert res[0].status is CrossResult.SINGLE
