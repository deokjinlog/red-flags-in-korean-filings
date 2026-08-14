"""성질 테스트 — 구조 분석에는 "정답" 이 없으므로 불변 성질을 검증한다."""
import random

import igraph as ig

from dartweave.structure.nullmodel import degree_preserving_null
from dartweave.structure.pipeline import AnalysisConfig, analyze
from dartweave.structure.verdict import Verdict


def _planted_blocks(k: int = 4, size: int = 8) -> list[tuple[str, str, str]]:
    """계획된 군집 구조 — 덩어리 k개가 다리로 느슨히 연결."""
    edges = []
    for b in range(k):
        members = [f"B{b}N{i}" for i in range(size)]
        for i in range(size):
            for j in range(i + 1, size):
                edges.append((members[i], members[j], "INVESTS_IN"))
        if b:
            edges.append((f"B{b-1}N0", members[0], "INVESTS_IN"))
    return edges


def test_planted_structure_beats_its_null():
    """실측 접지: 32노드 4블록에서 실제 0.7239 vs 귀무 0.2713 (효과 +0.4526)."""
    edges = _planted_blocks()
    g = ig.Graph.TupleList([(a, b) for a, b, _ in edges], directed=False)
    r = degree_preserving_null(g, runs=10, seed=1)
    assert r.actual > r.mean
    assert r.effect_size > 0.3
    assert r.swaps_failed == 0


def test_random_graph_yields_no_conclusion_not_a_crash():
    """무구조 입력에서 엔진이 죽지 않고 **확정 결론을 내지 않아야** 한다 (AC-10).

    시드를 고정해야 결정적이다 — ER 효과크기는 시드에 따라 -0.013 ~ +0.020 을
    오가고, 임계(0.05)에 가깝게 튀는 draw 가 실제로 관측됐다.
    실제로 이 시드에서 나오는 값은 `PARAMETER_DEPENDENT` 다 — 무구조 그래프는
    해상도에 따라 최대군집이 크게 흔들려 안정성 검사에서 먼저 걸린다.
    """
    ig.set_random_number_generator(random.Random(1))
    g = ig.Graph.Erdos_Renyi(n=40, m=120)
    edges = [
        (f"N{e.source}", f"N{e.target}", "INVESTS_IN") for e in g.es
    ]
    nodes = {v for e in edges for v in e[:2]}
    block = analyze(
        edges,
        interior=nodes,
        lens_name="governance",
        corporate_resolution_rate=1.0,
        config=AnalysisConfig(min_corporate_resolution_rate=0.0,
                              max_boundary_ratio=0.0, null_runs=5),
    )
    assert block.verdict in (Verdict.NO_CONCLUSION, Verdict.PARAMETER_DEPENDENT)


def test_degree_sequence_survives_shuffle():
    edges = _planted_blocks()
    g = ig.Graph.TupleList([(a, b) for a, b, _ in edges], directed=False)
    assert degree_preserving_null(g, runs=5, seed=1).degree_preserved


def test_effect_size_is_reported_alongside_z():
    """z 는 표준편차가 작으면 부풀려진다 — 효과크기를 함께 봐야 한다."""
    edges = _planted_blocks()
    g = ig.Graph.TupleList([(a, b) for a, b, _ in edges], directed=False)
    r = degree_preserving_null(g, runs=10, seed=1)
    assert hasattr(r, "z") and hasattr(r, "effect_size")
