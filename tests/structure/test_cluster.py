import igraph as ig

from dartweave.structure.cluster import ClusterResult, cluster, compare_objectives


def _two_blobs() -> ig.Graph:
    """두 덩어리가 다리 하나로 연결된 그래프 — 군집이 분명히 존재한다."""
    edges = [(i, j) for i in range(5) for j in range(i + 1, 5)]
    edges += [(i, j) for i in range(5, 10) for j in range(i + 1, 10)]
    edges.append((4, 5))
    return ig.Graph(n=10, edges=edges, directed=False)


def test_cluster_returns_membership_and_modularity():
    r = cluster(_two_blobs(), objective="modularity")
    assert isinstance(r, ClusterResult)
    assert r.n_clusters == 2
    assert r.modularity > 0


def test_cpm_objective_is_supported():
    """GDS Leiden 은 모듈러리티 전용이라 CPM 은 igraph 로만 된다 (요구사항 결정 7)."""
    r = cluster(_two_blobs(), objective="CPM", resolution=0.1)
    assert r.n_clusters >= 2


def test_membership_covers_every_node():
    g = _two_blobs()
    r = cluster(g, objective="modularity")
    assert len(r.membership) == g.vcount()


def test_compare_objectives_reports_the_delta():
    """모듈러리티가 작은 군집을 놓치는지 보는 게 목적이다 (실측 38 vs 52)."""
    c = compare_objectives(_two_blobs(), cpm_resolution=0.1)
    assert set(c) == {"modularity_clusters", "cpm_clusters", "delta"}
    assert c["delta"] == c["cpm_clusters"] - c["modularity_clusters"]


def test_seed_makes_result_reproducible():
    g = _two_blobs()
    a = cluster(g, objective="modularity", seed=7)
    b = cluster(g, objective="modularity", seed=7)
    assert a.membership == b.membership


def test_weighted_run_differs_from_unweighted():
    """AC-2 — 가중치가 실제로 군집에 영향을 준다는 걸 확인 가능해야 한다.

    실측: 다리에 200 을 주면 무가중 2군집 → 가중 3군집으로 갈라진다.
    가중치를 붙였는데 결과가 같으면 주입이 안 된 것이다.
    """
    g = _two_blobs()
    unweighted = cluster(g, objective="modularity", seed=1)

    g.es["weight"] = [1.0] * (g.ecount() - 1) + [200.0]
    weighted = cluster(g, objective="modularity", seed=1)

    assert weighted.membership != unweighted.membership
