"""정형 API 응답 → 관계 엣지. 이 경로의 엣지는 confidence 를 갖지 않는다."""
from __future__ import annotations

from typing import Any

from dartweave.parse.relation import EdgeType, RelationEdge, Source


def parse_ratio(raw: Any) -> float | None:
    """'-', '', '1,234.5' 같은 실제 응답 변형을 흡수한다. 실패는 0이 아니라 None."""
    text = str(raw or "").strip().replace(",", "")
    if not text or text == "-":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def normalize_as_of(raw: Any) -> str | None:
    text = str(raw or "").strip().replace("-", "").replace(".", "")
    return text if len(text) == 8 and text.isdigit() else None


def parse_major_shareholder(payload: dict[str, Any]) -> list[RelationEdge]:
    edges: list[RelationEdge] = []
    for item in payload.get("list", []):
        rcept_no = str(item.get("rcept_no", "")).strip()
        target = str(item.get("corp_code", "")).strip()
        edges.append(
            RelationEdge(
                edge_type=EdgeType.MAJOR_SHAREHOLDER_OF,
                source_name=str(item.get("nm", "")).strip(),
                source_corp_code=None,
                target_name=None,
                target_corp_code=target,
                rcept_no=rcept_no,
                fiscal_year=rcept_no[:4],
                as_of=normalize_as_of(item.get("stlm_dt")),
                source=Source.STRUCTURED,
                share_pct=parse_ratio(item.get("trmend_posesn_stock_qota_rt")),
                reporter_corp_code=target,
            )
        )
    return edges


def parse_investment(payload: dict[str, Any]) -> list[RelationEdge]:
    """타법인 출자현황 — 신고 주체가 보유자다 (최대주주 현황과 방향이 반대)."""
    edges: list[RelationEdge] = []
    for item in payload.get("list", []):
        rcept_no = str(item.get("rcept_no", "")).strip()
        holder = str(item.get("corp_code", "")).strip()
        edges.append(
            RelationEdge(
                edge_type=EdgeType.INVESTS_IN,
                source_name="",
                source_corp_code=holder,
                target_name=str(item.get("inv_prm", "")).strip(),
                target_corp_code=None,
                rcept_no=rcept_no,
                fiscal_year=rcept_no[:4],
                as_of=normalize_as_of(item.get("stlm_dt")),
                source=Source.STRUCTURED,
                share_pct=parse_ratio(item.get("trmend_qota_rt")),
                reporter_corp_code=holder,
            )
        )
    return edges


def parse_major_holding(payload: dict[str, Any]) -> list[RelationEdge]:
    """지분공시(5% 룰) — 최대주주 현황과 맞대볼 상대."""
    edges: list[RelationEdge] = []
    for item in payload.get("list", []):
        rcept_no = str(item.get("rcept_no", "")).strip()
        target = str(item.get("corp_code", "")).strip()
        edges.append(
            RelationEdge(
                edge_type=EdgeType.HOLDS_5PCT,
                source_name=str(item.get("repror", "")).strip(),
                source_corp_code=None,
                target_name=None,
                target_corp_code=target,
                rcept_no=rcept_no,
                fiscal_year=rcept_no[:4],
                as_of=normalize_as_of(item.get("stlm_dt")),
                source=Source.STRUCTURED,
                share_pct=parse_ratio(item.get("stkqy_irds_rt")),
                reporter_corp_code=target,
            )
        )
    return edges
