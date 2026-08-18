"""시점 조회 — look-ahead 를 구조로 막는다.

이 파일이 지키는 계약은 하나다: **T 시점 신호를 계산할 때 T 이후에 나온 공시가
섞이면 안 된다.** 섞이면 미래를 훔쳐본 것이고, 그 위에서 한 검정은 전부 무효다.

시나리오는 실제로 흔한 형태다 — 사실 기준일은 같은데 정정공시가 몇 달 뒤에 온다.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from dartweave.db.asof import (
    LookAheadError,
    assert_no_look_ahead,
    events_after,
    facts_known_at,
    latest_edges_at,
)
from dartweave.db.models import Base, DistressEvent, RelationFact


def _fact(rcept_no, as_of, rcept_dt, pct):
    return RelationFact(
        rcept_no=rcept_no, source_corp_code="A", target_corp_code="B",
        rel_type="INVESTS_IN", stock_knd="", as_of=as_of, rcept_dt=rcept_dt,
        share_pct=pct, share_qty=None, is_structured=True, cross_confirmed=False,
    )


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        # 2022-12 기준 지분을 2023-03 에 30% 로 신고했다가 2023-08 에 25% 로 정정
        s.add_all([_fact("20230301000001", "20221231", "20230301", 30.0),
                   _fact("20230801000001", "20221231", "20230801", 25.0)])
        s.add(DistressEvent(rcept_no="20240226006299", corp_code="A",
                            event_type="부도발생", rcept_dt="20240226", detail={}))
        s.commit()
        yield s


def test_correction_is_invisible_before_it_was_filed(session):
    """2023-05 에 세상이 알던 값은 30% 다. 25% 는 그때 존재하지 않았다."""
    known = facts_known_at(session, "20230501")
    assert [f.share_pct for f in known] == [30.0]


def test_correction_appears_after_it_was_filed(session):
    assert {f.share_pct for f in facts_known_at(session, "20230901")} == {30.0, 25.0}


def test_latest_wins_but_only_among_what_was_known(session):
    """정정 전에는 원래 값이, 정정 후에는 정정값이 최신이다."""
    assert latest_edges_at(session, "20230501")[("A", "B", "INVESTS_IN", "")].share_pct == 30.0
    assert latest_edges_at(session, "20230901")[("A", "B", "INVESTS_IN", "")].share_pct == 25.0


def test_original_row_is_never_overwritten(session):
    """append-only — 정정이 와도 원래 행이 남아야 '그때 알던 값' 을 복원할 수 있다."""
    assert len(facts_known_at(session, "20991231")) == 2


def test_as_of_alone_would_leak_the_future(session):
    """회귀 방지 — `rcept_dt` 조건을 빼면 정정값이 딸려 온다.

    두 행 모두 as_of 가 20221231 이라, as_of 만 걸면 2023-05 조회에 25% 가 섞인다.
    그게 미래를 훔쳐보는 정확한 형태다.
    """
    rows = session.query(RelationFact).filter(RelationFact.as_of <= "20230501").all()
    assert len(rows) == 2                                   # as_of 만 걸면 둘 다
    assert len(facts_known_at(session, "20230501")) == 1     # 두 조건 다 걸면 하나


def test_labels_come_from_after_the_feature_date(session):
    assert len(events_after(session, "20240101")) == 1
    assert events_after(session, "20240301") == []


def test_label_window_can_be_bounded(session):
    assert len(events_after(session, "20240101", within_days=60)) == 1
    assert events_after(session, "20240101", within_days=30) == []


def test_feature_date_must_precede_label_date():
    assert_no_look_ahead("20230101", "20240101")
    with pytest.raises(LookAheadError):
        assert_no_look_ahead("20240101", "20230101")
    with pytest.raises(LookAheadError):
        assert_no_look_ahead("20240101", "20240101")


def test_malformed_date_is_rejected(session):
    with pytest.raises(ValueError):
        facts_known_at(session, "2024-01-01")
