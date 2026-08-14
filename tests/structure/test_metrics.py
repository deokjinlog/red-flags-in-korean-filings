from dartweave.structure.metrics import cluster_metrics

# 군집 0 = {A,B}, 군집 1 = {C,D}. 다리 하나(B-C).
EDGES = [
    ("A", "B", "INVESTS_IN"),
    ("C", "D", "INVESTS_IN"),
    ("B", "C", "INVESTS_IN"),
]
MEMBERSHIP = {"A": 0, "B": 0, "C": 1, "D": 1}


def test_internal_and_external_edges_are_separated():
    rows = {r.cluster_id: r for r in cluster_metrics(EDGES, MEMBERSHIP, depth={})}
    assert rows[0].internal_edges == 1
    assert rows[0].external_edges == 1


def test_dependency_ratio_is_external_over_nodes():
    rows = {r.cluster_id: r for r in cluster_metrics(EDGES, MEMBERSHIP, depth={})}
    assert rows[0].dependency_ratio == 0.5  # 외부 1 / 노드 2


def test_mean_depth_uses_supplied_depths():
    depth = {"A": 0.0, "B": 0.5, "C": 0.5, "D": 1.0}
    rows = {r.cluster_id: r for r in cluster_metrics(EDGES, MEMBERSHIP, depth=depth)}
    assert rows[0].mean_supply_depth == 0.25


def test_missing_depth_yields_none_not_zero():
    """깊이를 못 구한 걸 0(순수 상류)으로 치면 없는 결론이 생긴다."""
    rows = {r.cluster_id: r for r in cluster_metrics(EDGES, MEMBERSHIP, depth={})}
    assert rows[0].mean_supply_depth is None


def test_cluster_rows_have_no_semantic_label():
    """AC-4 — 군집 번호와 수치만. '소재 군집' 같은 이름을 만들지 않는다."""
    row = cluster_metrics(EDGES, MEMBERSHIP, depth={})[0]
    assert set(vars(row)) == {
        "cluster_id",
        "nodes",
        "internal_edges",
        "external_edges",
        "dependency_ratio",
        "mean_supply_depth",
    }
