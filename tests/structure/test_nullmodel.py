import igraph as ig

from dartweave.structure.nullmodel import NullResult, degree_preserving_null


def _two_blobs() -> ig.Graph:
    edges = [(i, j) for i in range(6) for j in range(i + 1, 6)]
    edges += [(i, j) for i in range(6, 12) for j in range(i + 1, 12)]
    edges.append((5, 6))
    return ig.Graph(n=12, edges=edges, directed=False)


def test_shuffle_preserves_degree_sequence():
    """완전 무작위 셔플은 허브까지 없애 귀무모형을 부당하게 낮춘다."""
    g = _two_blobs()
    r = degree_preserving_null(g, runs=3, seed=1)
    assert r.degree_preserved is True


def test_structured_graph_scores_above_its_null():
    g = _two_blobs()
    r = degree_preserving_null(g, runs=10, seed=1)
    assert isinstance(r, NullResult)
    assert r.actual > r.mean
    assert r.z > 0


def test_runs_count_is_reported():
    """AC-5 — 반복 횟수가 출력에 명시돼야 한다."""
    r = degree_preserving_null(_two_blobs(), runs=7, seed=1)
    assert r.runs == 7


def test_random_graph_has_small_effect_size():
    """무구조 그래프는 귀무모형과 구분되지 않아야 한다.

    z 가 아니라 효과크기로 본다 — sd 가 작으면 z 는 무구조에서도 크게 뜬다.
    """
    ig.set_random_number_generator(__import__("random").Random(1))
    g = ig.Graph.Erdos_Renyi(n=40, m=120)
    r = degree_preserving_null(g, runs=8, seed=1)
    assert abs(r.effect_size) < 0.05


def test_graph_too_small_to_shuffle_is_reported_not_swallowed():
    """4노드 미만은 셔플 자체가 불가능하다 (nx.NetworkXError).

    실측: 삼각형은 3회 시도 3회 실패 → 귀무 = 실제 → 효과크기 0.
    조용히 통과시키면 '구조 없음' 과 '판정 불가' 가 구분되지 않는다.
    """
    tri = ig.Graph(n=3, edges=[(0, 1), (1, 2), (2, 0)], directed=False)
    r = degree_preserving_null(tri, runs=3, seed=1)
    assert r.swaps_failed == 3
    assert r.effect_size == 0.0
