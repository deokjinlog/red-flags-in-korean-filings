from dartweave.db.models import Base


def test_all_tables_defined():
    names = set(Base.metadata.tables)
    assert names == {
        "company",
        "disclosure",
        "extraction_run",
        "precision_sample",
        "precision_table",
        "entity_alias",
        "unresolved_mention",
        "relation_change",
        "contradiction",
    }


def test_company_requires_select_reason_column():
    cols = Base.metadata.tables["company"].columns
    assert "selected" in cols and "select_reason" in cols


def test_disclosure_records_failure_reason():
    cols = Base.metadata.tables["disclosure"].columns
    assert "fetch_status" in cols and "fail_reason" in cols


def test_contradiction_has_verdict_slot():
    cols = Base.metadata.tables["contradiction"].columns
    assert "grade" in cols and "verdict" in cols
