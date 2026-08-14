import pytest

from dartweave.structure.project import boundary_of, project
from dartweave.structure.topology import BoundaryNotClosed, topology

EDGES = [("A", "B", "INVESTS_IN"), ("B", "C", "INVESTS_IN")]
CLOSED = {"A", "B", "C"}


def test_topology_reports_in_and_out_degree_separately():
    g = project(EDGES, undirected=False)
    t = topology(g, boundary_of(EDGES, CLOSED), max_boundary_ratio=0.0)
    assert t.out_degree["A"] == 1 and t.in_degree["A"] == 0
    assert t.in_degree["C"] == 1 and t.out_degree["C"] == 0


def test_supply_depth_places_source_upstream():
    g = project(EDGES, undirected=False)
    t = topology(g, boundary_of(EDGES, CLOSED), max_boundary_ratio=0.0)
    assert t.depth["A"] < t.depth["C"]


def test_open_boundary_refuses_to_compute():
    """AC-14 — 경계가 열린 상태의 방향 지표는 틀린 결론을 낸다."""
    g = project(EDGES, undirected=False)
    with pytest.raises(BoundaryNotClosed) as ei:
        topology(g, boundary_of(EDGES, {"A"}), max_boundary_ratio=0.1)
    assert "경계" in str(ei.value)


def test_betweenness_is_included_when_closed():
    g = project(EDGES, undirected=False)
    t = topology(g, boundary_of(EDGES, CLOSED), max_boundary_ratio=0.0)
    assert t.betweenness["B"] > t.betweenness["A"]


def test_no_cluster_label_is_produced():
    """AC-4 — 군집에 의미 라벨을 붙이는 경로가 없어야 한다."""
    g = project(EDGES, undirected=False)
    t = topology(g, boundary_of(EDGES, CLOSED), max_boundary_ratio=0.0)
    assert not hasattr(t, "labels")
