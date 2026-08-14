from dartweave.structure.project import BoundaryReport, boundary_of, project

EDGES = [("A", "B", "INVESTS_IN"), ("B", "C", "INVESTS_IN")]


def test_natural_projection_keeps_direction():
    g = project(EDGES, undirected=False)
    assert g.is_directed()
    assert g.ecount() == 2


def test_undirected_projection_drops_direction():
    """Leiden 은 UNDIRECTED 를 요구한다 (요구사항 결정 3)."""
    g = project(EDGES, undirected=True)
    assert not g.is_directed()


def test_weights_are_attached_when_given():
    g = project(EDGES, undirected=False, weights=[2.0, 3.0])
    assert list(g.es["weight"]) == [2.0, 3.0]


def test_boundary_ratio_counts_nodes_without_own_filing():
    """자기 신고가 없는 노드 = 경계. 실측에서 이게 출입차수를 왜곡했다."""
    r = boundary_of(EDGES, interior={"A", "B"})
    assert isinstance(r, BoundaryReport)
    assert r.total == 3 and r.boundary == 1
    assert r.ratio == 1 / 3


def test_fully_closed_graph_has_zero_boundary():
    r = boundary_of(EDGES, interior={"A", "B", "C"})
    assert r.ratio == 0.0 and r.is_closed(max_ratio=0.0)


def test_is_closed_respects_threshold():
    r = boundary_of(EDGES, interior={"A", "B"})
    assert not r.is_closed(max_ratio=0.1)
    assert r.is_closed(max_ratio=0.5)
