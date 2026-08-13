"""멱등 적재용 Cypher 생성.

- MERGE 복합 키: (시작, 끝, 타입, fiscal_year, source) — 재적재가 중복을 만들지 않는다
- evidence_weight 는 저장하지 않는다 (D5). 인자만 남기고 투영 직전 계산한다
- 해소되지 않은 대상은 노드를 만들지 않고 예외로 막는다 (AC-10)
"""
from __future__ import annotations

from typing import Any

from dartweave.parse.relation import EdgeType, RelationEdge

_COMPANY_TARGET_TYPES = {
    EdgeType.MAJOR_SHAREHOLDER_OF,
    EdgeType.INVESTS_IN,
    EdgeType.HOLDS_5PCT,
}


def _require(value: str | None, what: str, edge: RelationEdge) -> str:
    if not value:
        raise ValueError(
            f"{what} 가 해소되지 않았습니다 ({edge.edge_type.value}, {edge.rcept_no}). "
            "미해소는 대기열로 보내야 하며 신규 노드를 만들지 않습니다."
        )
    return value


def build_edge_merge(
    edge: RelationEdge, *, mention_count: int
) -> tuple[str, dict[str, Any]]:
    # ⚠️ RISK(breaking): 아래 MERGE 키(fiscal_year·source·as_of)가 곧 엣지의 정체성이다.
    # 이 조합을 나중에 바꾸면 기존 엣지와 매칭이 안 돼 재적재가 중복 엣지를 만든다
    # (테스트로는 안 잡힌다 — 빈 DB에서는 항상 통과하므로). 변경 시 기존 그래프 삭제 후 전량 재적재할 것.
    # — by main(3-checklist: 식별 키 변경 = 하위호환 파괴)
    # 양쪽 모두 해소된 corp_code 를 요구한다. 슬라이스 1의 엣지는 전부 Company↔Company 다.
    start_code = _require(edge.source_corp_code, "시작 노드", edge)
    end_code = _require(edge.target_corp_code, "끝 노드", edge)

    cypher = f"""
    MATCH (a:Company {{corp_code: $start_code}})
    MATCH (b:Company {{corp_code: $end_code}})
    MERGE (a)-[r:{edge.edge_type.value} {{
        fiscal_year: $fiscal_year,
        source: $source,
        as_of: $as_of
    }}]->(b)
    SET r.rcept_no = $rcept_no,
        r.mention_count = $mention_count,
        r.share_pct = $share_pct,
        r.confidence = $confidence,
        r.cross_confirmed = $cross_confirmed,
        r.counterpart_rcept_no = $counterpart_rcept_no
    RETURN r
    """.strip()

    params: dict[str, Any] = {
        "start_code": start_code,
        "end_code": end_code,
        "rcept_no": edge.rcept_no,
        "as_of": edge.as_of,
        "fiscal_year": edge.fiscal_year,
        "source": edge.source.value,
        "mention_count": mention_count,
        "share_pct": edge.share_pct,
        "confidence": edge.confidence,
        "cross_confirmed": False,
        "counterpart_rcept_no": None,
    }
    return cypher, params
