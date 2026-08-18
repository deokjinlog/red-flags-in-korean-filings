"""Postgres 원장. 그래프는 Neo4j 가 맡고, 여기는 상태·이력·검수만 담는다."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


# ⚠️ RISK(breaking): 마이그레이션 도구가 없다. 스키마는 create_all 로만 만들어지므로
# 아래 컬럼을 나중에 바꾸면 기존 DB에 자동 반영되지 않는다 (조용히 어긋난 채로 돈다).
# 컬럼 변경 시 docker compose down -v 로 볼륨을 비우거나 마이그레이션을 도입할 것.
# — by main(3-checklist: public schema change)
class Base(DeclarativeBase):
    pass


class Company(Base):
    __tablename__ = "company"
    corp_code: Mapped[str] = mapped_column(String(8), primary_key=True)
    corp_name: Mapped[str] = mapped_column(String(200))
    stock_code: Mapped[str | None] = mapped_column(String(6))
    corp_cls: Mapped[str | None] = mapped_column(String(1))
    induty_code: Mapped[str | None] = mapped_column(String(10))
    selected: Mapped[bool] = mapped_column(Boolean, default=False)
    # AC-1: 선정 사유를 컬럼으로 강제 — 수동 보정이 기록 없이 일어나는 걸 막는다
    select_reason: Mapped[str | None] = mapped_column(Text)


class Disclosure(Base):
    __tablename__ = "disclosure"
    rcept_no: Mapped[str] = mapped_column(String(14), primary_key=True)
    corp_code: Mapped[str] = mapped_column(String(8), index=True)
    report_nm: Mapped[str] = mapped_column(String(300))
    rcept_dt: Mapped[str] = mapped_column(String(8))
    fiscal_year: Mapped[str] = mapped_column(String(4), index=True)
    as_of: Mapped[str | None] = mapped_column(String(8))
    fetch_status: Mapped[str] = mapped_column(String(20), default="pending")
    # AC-2: 실패를 침묵으로 넘기지 않는다
    fail_reason: Mapped[str | None] = mapped_column(Text)


class ExtractionRun(Base):
    __tablename__ = "extraction_run"
    run_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    model: Mapped[str] = mapped_column(String(100))
    prompt_version: Mapped[str] = mapped_column(String(50))
    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class PrecisionSample(Base):
    __tablename__ = "precision_sample"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    edge_key: Mapped[str] = mapped_column(String(300), index=True)
    rcept_no: Mapped[str] = mapped_column(String(14))
    snippet: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float)
    verdict: Mapped[str | None] = mapped_column(String(20))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime)


class PrecisionTable(Base):
    __tablename__ = "precision_table"
    conf_bucket: Mapped[str] = mapped_column(String(20), primary_key=True)
    n_sample: Mapped[int] = mapped_column(Integer, default=0)
    n_correct: Mapped[int] = mapped_column(Integer, default=0)
    observed_precision: Mapped[float | None] = mapped_column(Float)


class EntityAlias(Base):
    __tablename__ = "entity_alias"
    surface_form: Mapped[str] = mapped_column(String(300), primary_key=True)
    corp_code: Mapped[str] = mapped_column(String(8), index=True)
    source: Mapped[str] = mapped_column(String(10), default="auto")
    added_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class UnresolvedMention(Base):
    __tablename__ = "unresolved_mention"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    surface_form: Mapped[str] = mapped_column(String(300), index=True)
    rcept_no: Mapped[str] = mapped_column(String(14))
    snippet: Mapped[str | None] = mapped_column(Text)
    occurrences: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(20), default="open")


class RelationChange(Base):
    """결정 5 — 시점차는 버리지 않고 여기 적립한다."""

    __tablename__ = "relation_change"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    edge_key: Mapped[str] = mapped_column(String(300), index=True)
    from_fiscal_year: Mapped[str] = mapped_column(String(4))
    to_fiscal_year: Mapped[str] = mapped_column(String(4))
    from_value: Mapped[str | None] = mapped_column(String(100))
    to_value: Mapped[str | None] = mapped_column(String(100))
    from_rcept_no: Mapped[str] = mapped_column(String(14))
    to_rcept_no: Mapped[str] = mapped_column(String(14))


class Contradiction(Base):
    """결정 6 — 모순 검출 결과의 영구 기록. verdict 는 층2 워크벤치가 채운다."""

    __tablename__ = "contradiction"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    grade: Mapped[str] = mapped_column(String(1), index=True)
    edge_key: Mapped[str] = mapped_column(String(300), index=True)
    detail: Mapped[dict] = mapped_column(JSON)
    detected_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    verdict: Mapped[str | None] = mapped_column(String(20))
    verdict_by: Mapped[str | None] = mapped_column(String(100))


class RelationFact(Base):
    """관계 사실 하나 — **append-only**. 정정공시가 와도 덮어쓰지 않는다.

    두 시점을 분리해서 갖는 게 이 테이블의 존재 이유다.
      `as_of`     사실 기준일 — 이 지분율이 언제 기준인가
      `rcept_dt`  공시 시점   — 그 사실을 언제 알게 됐나

    왜 분리하나: "T 시점 신호가 이후 부실을 예고했나" 를 검정하려면 **T 시점에 알 수
    있었던 것만** 써야 한다. 정정공시는 as_of 가 과거인데 rcept_dt 는 나중이다.
    덮어쓰면 그 구분이 사라지고 미래 정보가 새어들어 검정이 통째로 무효가 된다.

    기본키에 `rcept_no` 가 들어가므로 정정공시는 자연히 새 행이 된다.
    """

    __tablename__ = "relation_fact"
    rcept_no: Mapped[str] = mapped_column(String(14), primary_key=True)
    source_corp_code: Mapped[str] = mapped_column(String(8), primary_key=True, index=True)
    target_corp_code: Mapped[str] = mapped_column(String(8), primary_key=True, index=True)
    rel_type: Mapped[str] = mapped_column(String(40), primary_key=True)
    stock_knd: Mapped[str] = mapped_column(String(40), primary_key=True, default="")
    as_of: Mapped[str] = mapped_column(String(8), index=True)
    rcept_dt: Mapped[str] = mapped_column(String(8), index=True)
    share_pct: Mapped[float | None] = mapped_column(Float)
    share_qty: Mapped[int | None] = mapped_column(Integer)
    is_structured: Mapped[bool] = mapped_column(Boolean, default=True)
    cross_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)


class DistressEvent(Base):
    """부실 사건 라벨 — 부도·회생·관리절차·영업정지.

    실측(2024 1분기): 주요사항보고 1,809건 중 부실 관련 16건. 연간 추정 96건이고
    그중 부도급이 50건 수준이다. 예측 모델에는 부족하고 신호 검정에는 쓸 수 있다.
    """

    __tablename__ = "distress_event"
    rcept_no: Mapped[str] = mapped_column(String(14), primary_key=True)
    corp_code: Mapped[str] = mapped_column(String(8), index=True)
    event_type: Mapped[str] = mapped_column(String(40), index=True)
    rcept_dt: Mapped[str] = mapped_column(String(8), index=True)
    detail: Mapped[dict] = mapped_column(JSON)
