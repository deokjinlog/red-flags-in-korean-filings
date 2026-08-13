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
    # 실데이터 반영: 지분율 합계 100% 규칙은 주식 종류별로 성립한다.
    # 종류를 섞어 합산하면 같은 지분이 "보통주"/"의결권 있는 주식" 으로 중복 게시된
    # 회사에서 합계가 두 배로 튀어 가짜 1급 모순이 만들어진다.
    stock_knd: str | None = None
    # 실데이터 반영: 지분율은 분모가 신고서마다 다르다.
    # 「최대주주 현황」은 주식종류별(보통주) 기준, 「타법인 출자현황」은 총발행주식 기준 —
    # 같은 298,818,100주가 5.01% 와 4.4% 로 갈린다. 주식수는 분모가 없어 해석의 여지가 없다.
    share_qty: int | None = None

    @property
    def edge_key(self) -> str:
        """엣지 정체성. mention_count 집계·모순 기록의 키."""
        src = self.source_corp_code or self.source_name
        tgt = self.target_corp_code or self.target_name or ""
        return f"{src}|{self.edge_type.value}|{tgt}"
