"""다중검정 보정 — 많이 재면 하나쯤은 우연히 유의해진다."""
from dartweave.signal.multiplicity import adjust


def test_empty_family_is_not_an_error():
    assert adjust([]) == []


def test_bonferroni_is_stricter_than_fdr():
    """같은 가족에서 Bonferroni 통과는 BH 통과의 부분집합이어야 한다."""
    fam = [(f"s{i}", p) for i, p in enumerate([0.0002, 0.001, 0.01, 0.02, 0.3])]
    out = adjust(fam)
    assert {a.name for a in out if a.bonferroni} <= {a.name for a in out if a.fdr}


def test_fdr_rejects_from_the_bottom_up():
    """중간에 하나 어긋나도 그 아래는 살아야 한다 — 항목별 비교면 잃는다.

    m=5, alpha=0.05 → 임계 0.01·0.02·0.03·0.04·0.05.
    0.025 는 자기 임계(0.03) 아래이므로 i=3 까지 기각되고, 0.019 도 함께 산다.
    """
    out = {a.name: a.fdr for a in adjust(
        [("a", 0.001), ("b", 0.019), ("c", 0.025), ("d", 0.9), ("e", 0.95)])}
    assert out["a"] and out["b"] and out["c"]
    assert not out["d"] and not out["e"]


def test_a_lone_marginal_result_does_not_survive_a_large_family():
    """20번 재서 하나 p=0.04 나온 건 우연으로도 일어난다."""
    fam = [("hit", 0.04)] + [(f"miss{i}", 0.5) for i in range(19)]
    out = {a.name: a for a in adjust(fam)}
    assert not out["hit"].bonferroni and not out["hit"].fdr


def test_family_size_is_recorded_in_the_threshold():
    out = adjust([("a", 0.001), ("b", 0.5)])
    assert out[0].threshold == 0.05 / 2 * 1 and out[0].rank == 1
