import pytest

from dartweave.structure.lens import LENSES, Lens, apply_lens


def test_lens_holds_only_include_list():
    """AC-1 — 중간 가중치 상수가 존재하면 안 된다. 필드 자체를 두지 않는다."""
    for lens in LENSES.values():
        assert set(vars(lens)) == {"name", "include"}


def test_known_lenses_exist():
    assert set(LENSES) == {"supply", "governance", "people"}
    assert LENSES["governance"].include == frozenset(
        {"MAJOR_SHAREHOLDER_OF", "INVESTS_IN", "HOLDS_5PCT"}
    )


def test_apply_lens_keeps_only_included_types():
    edges = [("A", "B", "INVESTS_IN"), ("B", "C", "SUPPLIES_TO")]
    kept = apply_lens(edges, LENSES["governance"])
    assert kept == [("A", "B", "INVESTS_IN")]


def test_apply_lens_is_binary_not_weighted():
    """살리거나 죽이거나. 남은 엣지에 렌즈발 가중치가 붙지 않는다."""
    edges = [("A", "B", "INVESTS_IN")]
    assert apply_lens(edges, LENSES["governance"]) == edges


def test_unknown_lens_name_raises_with_available_list():
    from dartweave.structure.lens import resolve_lens

    with pytest.raises(ValueError) as ei:
        resolve_lens("nope")
    assert "supply" in str(ei.value)


def test_select_indices_lets_callers_filter_parallel_lists():
    """엣지와 근거(EdgeEvidence)는 같은 순서의 평행 리스트다.

    렌즈로 엣지만 거르면 근거와 어긋나 **가중치가 엉뚱한 엣지에 붙는다.**
    그래서 인덱스를 돌려주는 경로를 따로 둔다.
    """
    from dartweave.structure.lens import select_indices

    edges = [("A", "B", "SUPPLIES_TO"), ("B", "C", "INVESTS_IN"), ("C", "D", "HOLDS_5PCT")]
    assert select_indices(edges, LENSES["governance"]) == [1, 2]
