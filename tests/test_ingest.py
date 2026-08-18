"""관계 사실 적재 — append-only · 멱등 · 불완전 행 거부.

시계열은 같은 대상을 여러 번 긁게 되고, 중간에 끊기고, 정정공시가 온다.
그 셋을 다 견뎌야 한다.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from dartweave.db.asof import latest_edges_at
from dartweave.db.ingest import ingest_edges, rcept_date
from dartweave.db.models import Base, RelationFact
from dartweave.parse.relation import EdgeType, RelationEdge, Source

R = "INVESTS_IN"


def _edge(rcept_no, pct, as_of="20221231", tgt="B", tgt_code="B"):
    return RelationEdge(
        edge_type=EdgeType.INVESTS_IN, source_name="가", source_corp_code="A",
        target_name="나", target_corp_code=tgt_code, rcept_no=rcept_no,
        fiscal_year=rcept_no[:4], as_of=as_of, source=Source.STRUCTURED,
        share_pct=pct,
    )


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def test_rcept_date_comes_from_the_receipt_number():
    """실측: 태영건설 부도공시 20240226006299 = 2024-02-26."""
    assert rcept_date("20240226006299") == "20240226"


def test_edges_are_inserted(session):
    r = ingest_edges(session, [_edge("20230301000001", 30.0)], rel_type=R)
    assert (r.inserted, r.skipped_duplicate) == (1, 0)


def test_reingesting_the_same_filing_is_a_no_op(session):
    """중간에 끊겨 다시 돌려도 결과가 같아야 한다."""
    ingest_edges(session, [_edge("20230301000001", 30.0)], rel_type=R)
    r = ingest_edges(session, [_edge("20230301000001", 30.0)], rel_type=R)
    assert (r.inserted, r.skipped_duplicate) == (0, 1)
    assert session.query(RelationFact).count() == 1


def test_correction_becomes_a_new_row_not_an_overwrite(session):
    """정정공시는 접수번호가 달라 새 행이 된다 — 원래 값이 남아야 한다."""
    ingest_edges(session, [_edge("20230301000001", 30.0)], rel_type=R)
    ingest_edges(session, [_edge("20230801000001", 25.0)], rel_type=R)
    assert session.query(RelationFact).count() == 2
    # 정정 전 시점에는 원래 값이 보인다
    assert latest_edges_at(session, "20230501")[("A", "B", R, "")].share_pct == 30.0


def test_row_without_both_corp_codes_is_rejected(session):
    """이름만 있는 행을 넣으면 나중에 해소된 코드와 짝이 안 맞아 노드가 갈라진다."""
    e = _edge("20230301000001", 30.0, tgt_code=None)
    r = ingest_edges(session, [e], rel_type=R)
    assert (r.inserted, r.skipped_incomplete) == (0, 1)


def test_as_of_falls_back_to_the_filing_date(session):
    """사실 기준일이 없으면 공시일로 둔다 — 없는 값을 지어내지 않되 비우지도 않는다."""
    e = _edge("20230301000001", 30.0, as_of=None)
    ingest_edges(session, [e], rel_type=R)
    row = session.query(RelationFact).one()
    assert row.as_of == "20230301" == row.rcept_dt


def test_same_filing_different_targets_are_separate_rows(session):
    r = ingest_edges(session, [_edge("20230301000001", 30.0, tgt_code="B"),
                               _edge("20230301000001", 10.0, tgt_code="C")], rel_type=R)
    assert r.inserted == 2
