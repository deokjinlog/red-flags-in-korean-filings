"""시점 조회 — "T 시점에 알 수 있었던 것" 을 한 곳에 가둔다.

왜 함수로 가두나:
  손으로 SQL 을 쓰게 두면 언젠가 조건 하나를 빠뜨린다. `as_of` 만 걸고 `rcept_dt`
  를 빠뜨리면 **나중에 정정된 값이 딸려 오고**, 그러면 미래를 훔쳐본 신호로 검정을
  하게 된다. 예측 연구를 망치는 가장 흔한 방식이 이것이다.

  층1이 게이트를 계산 **앞**에 둔 것과 같은 이유다 — 규율은 문서가 아니라 구조로
  강제해야 지켜진다.

스냅샷 테이블을 만들지 않는 이유:
  만드는 순간 정정공시 반영이 어긋나고, 어긋난 걸 나중에 발견하기가 아주 어렵다.
  그때그때 접는 비용이 훨씬 싸다.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from dartweave.db.models import DistressEvent, RelationFact


class LookAheadError(ValueError):
    """미래 정보를 요구했을 때."""


def _check(as_of_date: str) -> str:
    if not (len(as_of_date) == 8 and as_of_date.isdigit()):
        raise ValueError(f"YYYYMMDD 형식이어야 한다: {as_of_date!r}")
    return as_of_date


def facts_known_at(session: Session, as_of_date: str) -> list[RelationFact]:
    """`as_of_date` 시점에 **공시까지 나와 있던** 관계 사실.

    두 조건을 함께 건다. 하나라도 빠지면 look-ahead 다.
      as_of    <= T   — 그 시점 이전의 사실만
      rcept_dt <= T   — 그 시점까지 공시된 것만  ← 이걸 빠뜨리는 게 전형적 사고
    """
    t = _check(as_of_date)
    stmt = select(RelationFact).where(
        RelationFact.as_of <= t, RelationFact.rcept_dt <= t
    )
    return list(session.scalars(stmt))


def latest_edges_at(
    session: Session, as_of_date: str
) -> dict[tuple[str, str, str, str], RelationFact]:
    """같은 관계가 여러 번 신고됐으면 **그 시점 기준 가장 최근 공시**만 남긴다.

    정정공시가 아직 안 나온 시점에서는 원래 값이 남는다 — 그게 그때 세상이
    알고 있던 값이다.
    """
    out: dict[tuple[str, str, str, str], RelationFact] = {}
    for f in facts_known_at(session, as_of_date):
        key = (f.source_corp_code, f.target_corp_code, f.rel_type, f.stock_knd)
        cur = out.get(key)
        if cur is None or (f.rcept_dt, f.rcept_no) > (cur.rcept_dt, cur.rcept_no):
            out[key] = f
    return out


def events_after(
    session: Session, as_of_date: str, *, within_days: int | None = None
) -> list[DistressEvent]:
    """`as_of_date` **이후**에 발생한 부실 사건 — 신호 검정의 정답지.

    특징은 T 이전만, 라벨은 T 이후만. 이 경계가 흐려지면 검정이 무의미해진다.
    """
    t = _check(as_of_date)
    stmt = select(DistressEvent).where(DistressEvent.rcept_dt > t)
    rows = list(session.scalars(stmt))
    if within_days is not None:
        from datetime import date, timedelta

        d0 = date(int(t[:4]), int(t[4:6]), int(t[6:8]))
        limit = (d0 + timedelta(days=within_days)).strftime("%Y%m%d")
        rows = [r for r in rows if r.rcept_dt <= limit]
    return rows


def assert_no_look_ahead(features_at: str, label_at: str) -> None:
    """특징 시점이 라벨 시점보다 늦으면 검정이 성립하지 않는다."""
    if _check(features_at) >= _check(label_at):
        raise LookAheadError(
            f"특징 시점 {features_at} 이 라벨 시점 {label_at} 보다 앞서지 않는다 — "
            "미래를 보고 예측한 셈이 된다."
        )
