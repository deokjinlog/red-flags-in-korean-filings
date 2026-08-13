"""Postgres 세션 팩토리."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from dartweave.config import Settings
from dartweave.db.models import Base


def make_engine(settings: Settings | None = None):
    s = settings or Settings.from_env()
    return create_engine(s.pg_dsn, pool_pre_ping=True)


def init_schema(engine) -> None:
    # ⚠️ RISK(side-effect): 실제 DB에 DDL 을 친다. scripts/run_stage.py 가 단계와 무관하게
    # 이걸 무조건 호출하므로, DB 가 안 떠 있으면 export 처럼 DB 가 필요 없는 단계도
    # raw traceback 으로 죽는다(exit 1, 설계상 의도한 친절한 안내에 도달 못 함).
    # 또한 create_all 은 기존 테이블의 컬럼 변경을 반영하지 않는다 — models.py 의 RISK 참조.
    # — by main(3-checklist: 공유 자원에 대한 DDL + 실패 경로 우회)
    Base.metadata.create_all(engine)


@contextmanager
def session_scope(engine) -> Iterator[Session]:
    with Session(engine) as s:
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
