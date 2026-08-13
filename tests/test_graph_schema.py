from dartweave.graph.schema import CONSTRAINTS, INDEXES, REQUIRED_EDGE_PROPS


def test_company_corp_code_is_unique():
    assert any("Company" in c and "corp_code" in c and "UNIQUE" in c.upper() for c in CONSTRAINTS)


def test_rcept_no_is_indexed_for_provenance_lookup():
    joined = " ".join(INDEXES)
    assert "rcept_no" in joined


def test_required_edge_props_match_ac3():
    assert REQUIRED_EDGE_PROPS == (
        "rcept_no",
        "as_of",
        "fiscal_year",
        "source",
        "mention_count",
    )


def test_all_statements_are_idempotent():
    for stmt in CONSTRAINTS + INDEXES:
        assert "IF NOT EXISTS" in stmt.upper(), f"재실행 불가: {stmt}"
