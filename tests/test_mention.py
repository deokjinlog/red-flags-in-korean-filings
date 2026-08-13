from dartweave.parse.relation import EdgeType, RelationEdge, Source
from dartweave.trust.mention import count_mentions

def _edge(reporter, rcept_no, report_kind):
    return RelationEdge(
        edge_type=EdgeType.MAJOR_SHAREHOLDER_OF,
        source_name="A",
        source_corp_code="001",
        target_name=None,
        target_corp_code="002",
        rcept_no=rcept_no,
        fiscal_year=rcept_no[:4],
        as_of=None,
        source=Source.STRUCTURED,
        reporter_corp_code=reporter,
    ), report_kind


def test_same_company_across_three_years_counts_as_one():
    """AC-3 — 같은 회사의 연차 반복은 근거가 세 겹이 된 게 아니라 복사다."""
    pairs = [
        _edge("001", "20240311000001", "사업보고서"),
        _edge("001", "20250311000001", "사업보고서"),
        _edge("001", "20260311000001", "사업보고서"),
    ]
    counts = count_mentions(pairs)
    assert counts["001|MAJOR_SHAREHOLDER_OF|002"] == 1


def test_two_different_companies_count_as_two():
    pairs = [
        _edge("001", "20250311000001", "사업보고서"),
        _edge("002", "20250311000009", "사업보고서"),
    ]
    assert count_mentions(pairs)["001|MAJOR_SHAREHOLDER_OF|002"] == 2


def test_different_report_kinds_count_separately():
    pairs = [
        _edge("001", "20250311000001", "사업보고서"),
        _edge("001", "20250401000002", "주요사항보고서"),
    ]
    assert count_mentions(pairs)["001|MAJOR_SHAREHOLDER_OF|002"] == 2


def test_mixed_case_company_dominates_over_year_repetition():
    pairs = [
        _edge("001", "20240311000001", "사업보고서"),
        _edge("001", "20250311000001", "사업보고서"),
        _edge("002", "20250311000009", "사업보고서"),
    ]
    assert count_mentions(pairs)["001|MAJOR_SHAREHOLDER_OF|002"] == 2
