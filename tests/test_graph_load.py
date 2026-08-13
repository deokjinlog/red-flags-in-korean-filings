import pytest

from dartweave.graph.load import build_edge_merge
from dartweave.graph.schema import REQUIRED_EDGE_PROPS
from dartweave.parse.relation import EdgeType, RelationEdge, Source


def _edge(**kw):
    base = dict(
        edge_type=EdgeType.MAJOR_SHAREHOLDER_OF,
        source_name="삼성생명보험",
        source_corp_code="001",
        target_name=None,
        target_corp_code="002",
        rcept_no="20250311000001",
        fiscal_year="2025",
        as_of="20241231",
        source=Source.STRUCTURED,
        share_pct=8.51,
    )
    base.update(kw)
    return RelationEdge(**base)


def test_uses_merge_not_create():
    cypher, _ = build_edge_merge(_edge(), mention_count=1)
    assert "MERGE" in cypher and "CREATE (" not in cypher


def test_merge_key_includes_fiscal_year_and_source():
    """재적재가 중복을 만들지 않도록 복합 키를 쓴다."""
    cypher, _ = build_edge_merge(_edge(), mention_count=1)
    assert "fiscal_year" in cypher and "source" in cypher


def test_all_required_props_present_in_params():
    _, params = build_edge_merge(_edge(), mention_count=3)
    for prop in REQUIRED_EDGE_PROPS:
        assert prop in params, f"필수 속성 누락: {prop}"
    assert params["mention_count"] == 3


def test_evidence_weight_is_not_persisted():
    """D5 — weight 는 저장하지 않는다. 인자만 저장한다."""
    cypher, params = build_edge_merge(_edge(), mention_count=1)
    assert "evidence_weight" not in cypher
    assert "evidence_weight" not in params


def test_edge_without_resolvable_target_raises():
    """미해소를 신규 노드로 조용히 만드는 경로가 없어야 한다 (AC-10)."""
    with pytest.raises(ValueError, match="해소"):
        build_edge_merge(_edge(target_corp_code=None, target_name="미상회사"), mention_count=1)
