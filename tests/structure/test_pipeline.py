import pytest

from dartweave.structure.pipeline import (
    AnalysisConfig,
    QualityGateFailed,
    analyze,
)
from dartweave.structure.topology import BoundaryNotClosed
from dartweave.structure.verdict import Verdict

EDGES = [("A", "B", "INVESTS_IN"), ("B", "C", "INVESTS_IN"), ("C", "A", "INVESTS_IN")]
INTERIOR = {"A", "B", "C"}


def test_quality_gate_blocks_before_any_computation():
    """AC-12 — 미달이면 '일단 돌려보고 판단' 을 허용하지 않는다."""
    cfg = AnalysisConfig(min_corporate_resolution_rate=0.9)
    with pytest.raises(QualityGateFailed) as ei:
        analyze(EDGES, interior=INTERIOR, lens_name="governance",
                corporate_resolution_rate=0.6, config=cfg)
    assert "0.6" in str(ei.value) or "60" in str(ei.value)


def test_open_boundary_keeps_clustering_and_drops_only_layering():
    """D2 — 군집은 경계에 견디고 방향 지표만 못 견딘다.

    통째로 예외를 던지면 멀쩡한 군집 결과까지 버리고, AC-14 가 요구하는
    "경계 비율이 출력에 명시된다" 를 지킬 출력 자체가 사라진다.
    실데이터의 경계 비율은 한 번 닫고도 48.6% 였다 — 통째 거부면 아무것도 못 낸다.
    """
    cfg = AnalysisConfig(min_corporate_resolution_rate=0.0, max_boundary_ratio=0.0,
                         null_runs=3)
    block = analyze(EDGES, interior={"A"}, lens_name="governance",
                    corporate_resolution_rate=1.0, config=cfg)

    assert block.topology_computed is False
    assert block.scope.boundary_ratio > 0          # AC-14 — 비율은 출력에 남는다
    assert block.clusters                           # 군집은 살아남았다
    assert all(c.mean_supply_depth is None for c in block.clusters)


def test_require_topology_turns_the_gate_back_into_an_error():
    """층위가 반드시 필요한 호출부는 조용한 미산출 대신 예외를 받아야 한다."""
    cfg = AnalysisConfig(min_corporate_resolution_rate=0.0, max_boundary_ratio=0.0,
                         require_topology=True)
    with pytest.raises(BoundaryNotClosed):
        analyze(EDGES, interior={"A"}, lens_name="governance",
                corporate_resolution_rate=1.0, config=cfg)


def test_closed_boundary_still_computes_layering():
    """반대편 고정 — 경계가 닫혔는데 층위를 안 내면 게이트가 과잉이다."""
    cfg = AnalysisConfig(min_corporate_resolution_rate=0.0, max_boundary_ratio=0.0,
                         null_runs=3)
    block = analyze(EDGES, interior=INTERIOR, lens_name="governance",
                    corporate_resolution_rate=1.0, config=cfg)
    assert block.topology_computed is True


def test_closed_graph_produces_an_evidence_block():
    cfg = AnalysisConfig(min_corporate_resolution_rate=0.0, max_boundary_ratio=0.0,
                         null_runs=3)
    block = analyze(EDGES, interior=INTERIOR, lens_name="governance",
                    corporate_resolution_rate=1.0, config=cfg)
    assert block.scope.boundary_ratio == 0.0
    assert isinstance(block.verdict, Verdict)


def test_lens_filters_edges_before_analysis():
    cfg = AnalysisConfig(min_corporate_resolution_rate=0.0, max_boundary_ratio=0.0,
                         null_runs=3)
    mixed = EDGES + [("A", "C", "SUPPLIES_TO")]
    block = analyze(mixed, interior=INTERIOR, lens_name="governance",
                    corporate_resolution_rate=1.0, config=cfg)
    assert block.include_types == sorted(["MAJOR_SHAREHOLDER_OF", "INVESTS_IN",
                                          "HOLDS_5PCT"])


def test_no_conclusion_is_returned_not_raised():
    """AC-10 — 결론 없음이 예외 경로가 아니다."""
    cfg = AnalysisConfig(min_corporate_resolution_rate=0.0, max_boundary_ratio=0.0,
                         null_runs=3)
    block = analyze(EDGES, interior=INTERIOR, lens_name="governance",
                    corporate_resolution_rate=1.0, config=cfg)
    assert block.verdict in set(Verdict)


def test_mismatched_evidence_length_is_rejected_loudly():
    """평행 리스트가 어긋나면 **가중치가 엉뚱한 엣지에 붙는다** — 조용히 넘기면 안 된다."""
    from dartweave.structure.weight import EdgeEvidence

    cfg = AnalysisConfig(min_corporate_resolution_rate=0.0, max_boundary_ratio=0.0)
    with pytest.raises(ValueError) as ei:
        analyze(EDGES, interior=INTERIOR, lens_name="governance",
                corporate_resolution_rate=1.0,
                evidence=[EdgeEvidence(True, False, 1, None, None)], config=cfg)
    assert "길이" in str(ei.value)


def test_coefficient_sweep_runs_only_when_evidence_is_supplied():
    """AC-8 — 근거 없이 계수를 흔들 수는 없다. '검사 안 함' 을 '버텼음' 으로 위장하지 않는다."""
    from dartweave.structure.weight import EdgeEvidence

    cfg = AnalysisConfig(min_corporate_resolution_rate=0.0, max_boundary_ratio=0.0,
                         null_runs=3)
    without = analyze(EDGES, interior=INTERIOR, lens_name="governance",
                      corporate_resolution_rate=1.0, config=cfg)
    assert without.coef_sweep_holds is False

    ev = [EdgeEvidence(True, False, 1, None, None) for _ in EDGES]
    with_ev = analyze(EDGES, interior=INTERIOR, lens_name="governance",
                      corporate_resolution_rate=1.0, evidence=ev, config=cfg)
    assert isinstance(with_ev.coef_sweep_holds, bool)


def test_thresholds_and_industry_reach_the_evidence_block():
    """AC-12 · AC-13 — 설정이 산출물까지 실려야 한다."""
    cfg = AnalysisConfig(min_corporate_resolution_rate=0.0, max_boundary_ratio=0.0,
                         null_runs=3, industry="건설")
    block = analyze(EDGES, interior=INTERIOR, lens_name="governance",
                    corporate_resolution_rate=1.0, config=cfg)
    assert block.scope.industry == "건설"
    assert block.thresholds.min_corporate_resolution_rate == 0.0
