import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from dartweave.dart.disclosure import DisclosureRow
from dartweave.db.ledger import upsert_companies, upsert_disclosures
from dartweave.db.models import Base, Company, Disclosure
from dartweave.select.targets import SelectedCompany


@pytest.fixture
def session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def test_upsert_company_records_reason(session):
    upsert_companies(session, [SelectedCompany("001", "에이사", "26110", "업종코드 부합")])
    row = session.get(Company, "001")
    assert row.selected is True
    assert row.select_reason == "업종코드 부합"


def test_upsert_company_is_idempotent(session):
    picked = [SelectedCompany("001", "에이사", "26110", "업종코드 부합")]
    upsert_companies(session, picked)
    upsert_companies(session, picked)
    assert len(session.scalars(select(Company)).all()) == 1


def test_upsert_disclosure_is_idempotent(session):
    rows = [DisclosureRow("20250311000001", "001", "사업보고서", "20250311", "2025")]
    upsert_disclosures(session, rows)
    upsert_disclosures(session, rows)
    assert len(session.scalars(select(Disclosure)).all()) == 1


def test_failure_reason_is_persisted(session):
    upsert_disclosures(
        session,
        [DisclosureRow("20250311000002", "001", "사업보고서", "20250311", "2025")],
        fetch_status="failed",
        fail_reason="원문 ZIP 404",
    )
    row = session.get(Disclosure, "20250311000002")
    assert row.fetch_status == "failed"
    assert row.fail_reason == "원문 ZIP 404"
