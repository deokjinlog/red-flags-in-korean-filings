import igraph as ig

from dartweave.structure.sensitivity import (
    DEFAULT_MAX_RATIO,
    RESOLUTIONS,
    SweepPoint,
    SweepResult,
    resolution_sweep,
)


def _two_blobs() -> ig.Graph:
    edges = [(i, j) for i in range(6) for j in range(i + 1, 6)]
    edges += [(i, j) for i in range(6, 12) for j in range(i + 1, 12)]
    edges.append((5, 6))
    return ig.Graph(n=12, edges=edges, directed=False)


def test_default_sweep_has_at_least_four_points():
    """AC-7 — 최소 4개 값."""
    assert len(RESOLUTIONS) >= 4


def test_sweep_reports_every_point():
    r = resolution_sweep(_two_blobs())
    assert isinstance(r, SweepResult)
    assert len(r.points) == len(RESOLUTIONS)
    assert {p.resolution for p in r.points} == set(RESOLUTIONS)


def test_stable_structure_holds_across_the_sweep():
    r = resolution_sweep(_two_blobs())
    assert r.holds is True


def test_wildly_varying_cluster_count_does_not_hold():
    """무구조 그래프는 해상도에 따라 최대군집 비중이 0.787→0.087 로 무너진다."""
    ig.set_random_number_generator(__import__("random").Random(1))
    r = resolution_sweep(ig.Graph.Erdos_Renyi(n=80, m=240))
    assert r.holds is False
    assert r.largest_ratio > 5


def test_measured_halving_case_is_rejected():
    """회귀 방지 — 게이트가 **자기 존재 이유인 사례**를 잡아야 한다.

    실측: 1,490 노드에서 해상도 0.5→2.0 에 최대군집 126→69.
    비중의 절대 차이로 재면 0.085-0.046 = 0.038 이라 어떤 임계도 통과한다.
    배율로 재야 1.83배가 드러난다.
    """
    from dartweave.structure.sensitivity import stability_ratio

    points = [
        SweepPoint(resolution=0.5, n_clusters=38, largest_cluster=126,
                   largest_share=126 / 1490, label="resolution=0.5"),
        SweepPoint(resolution=2.0, n_clusters=61, largest_cluster=69,
                   largest_share=69 / 1490, label="resolution=2.0"),
    ]
    ratio = stability_ratio(points)
    assert 1.8 < ratio < 1.9
    assert ratio > DEFAULT_MAX_RATIO  # 즉, holds=False


def test_stable_case_stays_under_the_threshold():
    """반대편도 고정 — 안 흔들리는 구조를 반려하면 게이트가 쓸모없어진다."""
    from dartweave.structure.sensitivity import stability_ratio

    points = [
        SweepPoint(resolution=r, n_clusters=2, largest_cluster=6, largest_share=0.5,
                   label=f"resolution={r}")
        for r in (0.5, 2.0)
    ]
    assert stability_ratio(points) == 1.0


def test_points_carry_cluster_count_and_largest():
    r = resolution_sweep(_two_blobs())
    p = r.points[0]
    assert p.n_clusters > 0 and p.largest_cluster > 0


# --- AC-8: 겹2 계수 스윕 -----------------------------------------------------


def _edges_and_evidence():
    from dartweave.structure.weight import EdgeEvidence

    edges, ev = [], []
    for b in range(2):
        members = [f"B{b}N{i}" for i in range(5)]
        for i in range(5):
            for j in range(i + 1, 5):
                edges.append((members[i], members[j], "INVESTS_IN"))
                ev.append(EdgeEvidence(True, False, 1, None, None))
    edges.append(("B0N4", "B1N0", "INVESTS_IN"))
    ev.append(EdgeEvidence(True, True, 5, None, None))  # 다리만 교차확인+반복언급
    return edges, ev


def test_coefficient_sweep_covers_default_cases():
    """AC-8 — 해상도뿐 아니라 겹2 계수도 흔들어야 한다."""
    from dartweave.structure.sensitivity import COEFFICIENT_CASES, coefficient_sweep

    edges, ev = _edges_and_evidence()
    r = coefficient_sweep(edges, ev)
    assert len(r.points) == len(COEFFICIENT_CASES) >= 3


def test_coefficient_sweep_reports_holds():
    from dartweave.structure.sensitivity import coefficient_sweep

    edges, ev = _edges_and_evidence()
    assert isinstance(coefficient_sweep(edges, ev).holds, bool)


def test_coefficient_case_labels_are_human_readable():
    """반려 사유를 사람이 읽어야 한다 — 어떤 계수에서 뒤집혔는지."""
    from dartweave.structure.sensitivity import coefficient_sweep

    edges, ev = _edges_and_evidence()
    labels = [p.label for p in coefficient_sweep(edges, ev).points]
    assert "baseline" in labels
    assert all(isinstance(x, str) and x for x in labels)
