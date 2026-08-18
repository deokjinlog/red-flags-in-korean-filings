"""관계 사실 적재 — append-only, 재개 가능, 멱등.

왜 append 인가:
  정정공시가 오면 새 행이 된다(기본키에 `rcept_no` 가 들어간다). 덮어쓰면
  "그때 알던 값" 이 사라져 시점 검정이 무효가 된다 — `db/asof.py` 참조.

왜 재개가 필요한가:
  연도 × 기업으로 수천 건이라 한 번에 안 끝난다. 중간에 끊겨도 이어서 받아야 하고,
  이미 받은 걸 다시 받아도 결과가 같아야 한다(멱등).
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from dartweave.db.models import RelationFact
from dartweave.parse.relation import RelationEdge


@dataclass(frozen=True)
class IngestResult:
    inserted: int
    skipped_duplicate: int
    skipped_incomplete: int


def rcept_date(rcept_no: str) -> str:
    """공시일은 접수번호 앞 8자리다 — 실측 확인(20240226006299 = 2024-02-26)."""
    return rcept_no[:8]


def ingest_edges(
    session: Session,
    edges: list[RelationEdge],
    *,
    rel_type: str,
    resolve: Callable[[str], str | None] | None = None,
) -> IngestResult:
    """엣지를 `relation_fact` 에 넣는다. 이미 있으면 건너뛴다(멱등).

    양쪽 corp_code 가 없으면 넣지 않는다 — 이름만 있는 행을 넣으면 나중에 해소된
    코드와 짝이 안 맞아 같은 관계가 두 노드로 갈라진다.

    **`resolve` 를 여기서 받는 이유**: 정형 공시는 상대편을 `corp_code` 가 아니라
    이름으로만 준다(`nm`·`inv_prm`). 호출부마다 해소기를 붙이게 뒀더니 같은 자리에
    세 번 걸렸다 — 실측에서 40개사 수집에 903건이 '코드미상' 으로 버려졌다.
    적재 계층 안에 두면 어느 경로로 들어와도 해소를 거친다.
    """
    ins = dup = incomplete = 0
    for e in edges:
        src = e.source_corp_code or (resolve(e.source_name) if resolve else None)
        tgt = e.target_corp_code or (
            resolve(e.target_name) if resolve and e.target_name else None
        )
        if not (src and tgt and e.rcept_no):
            incomplete += 1
            continue
        key = dict(
            rcept_no=e.rcept_no,
            source_corp_code=src,
            target_corp_code=tgt,
            rel_type=rel_type,
            stock_knd=e.stock_knd or "",
        )
        exists = session.scalar(
            select(RelationFact).filter_by(**key).limit(1)
        )
        if exists is not None:
            dup += 1
            continue
        session.add(RelationFact(
            **key,
            as_of=e.as_of or rcept_date(e.rcept_no),
            rcept_dt=rcept_date(e.rcept_no),
            share_pct=e.share_pct,
            share_qty=e.share_qty,
            is_structured=True,
            cross_confirmed=False,
        ))
        ins += 1
    session.flush()
    return IngestResult(ins, dup, incomplete)
