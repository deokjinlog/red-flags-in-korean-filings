"""관계 레코드 — 정형/본문 양쪽이 같은 형태로 수렴한다."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class EdgeType(Enum):
    MAJOR_SHAREHOLDER_OF = "MAJOR_SHAREHOLDER_OF"
    INVESTS_IN = "INVESTS_IN"
    HOLDS_5PCT = "HOLDS_5PCT"
    EXECUTIVE_OF = "EXECUTIVE_OF"
    AUDITED_BY = "AUDITED_BY"
    SUPPLIES_TO = "SUPPLIES_TO"
    PRODUCES = "PRODUCES"


class Source(Enum):
    STRUCTURED = "structured"
    TEXT = "text"


@dataclass(frozen=True)
class RelationEdge:
    edge_type: EdgeType
    source_name: str
    source_corp_code: str | None
    target_name: str | None
    target_corp_code: str | None
    rcept_no: str
    fiscal_year: str
    as_of: str | None
    source: Source
    share_pct: float | None = None
    confidence: float | None = None
    reporter_corp_code: str | None = None

    @property
    def edge_key(self) -> str:
        """엣지 정체성. mention_count 집계·모순 기록의 키."""
        src = self.source_corp_code or self.source_name
        tgt = self.target_corp_code or self.target_name or ""
        return f"{src}|{self.edge_type.value}|{tgt}"
