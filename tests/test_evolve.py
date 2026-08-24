"""규칙 진화 — 실제 결과가 채점한다."""
import random

from dartweave.signal.evolve import (
    Rule,
    crossover,
    fitness,
    mutate,
    random_rule,
)


def _cells(sig_hits, sig_n, ctl_hits, ctl_n, strata=1):
    return [([True] * sig_hits + [False] * (sig_n - sig_hits),
             [True] * ctl_hits + [False] * (ctl_n - ctl_hits))] * strata


def test_tiny_perfect_rule_loses_to_a_big_decent_one():
    """3사 100% 가 250사 34% 를 이기면 안 된다 — fitness 하한이 그걸 막는다."""
    tiny = fitness(Rule((("a",),)), _cells(3, 3, 10, 500))
    big = fitness(Rule((("b",),)), _cells(85, 250, 30, 500))
    assert tiny == 0.0            # 20건 미만이라 점수 자체가 없다
    assert big > 1.0


def test_min_positives_is_the_same_bar_as_the_judgement():
    assert fitness(Rule((("a",),)), _cells(19, 200, 10, 500)) == 0.0
    assert fitness(Rule((("a",),)), _cells(20, 200, 10, 500)) > 0.0


def test_lower_bound_shrinks_with_sample_size():
    """같은 배율이라도 표본이 작으면 점수가 낮아야 한다."""
    small = fitness(Rule((("a",),)), _cells(20, 100, 20, 500))
    large = fitness(Rule((("a",),)), _cells(100, 500, 100, 2500))
    assert large > small          # 배율은 같은데 큰 쪽이 높다


def test_empty_stratum_is_skipped_not_counted():
    """한쪽이 빈 층은 비교가 성립하지 않는다 — 세면 배율이 왜곡된다."""
    cells = _cells(30, 100, 20, 400) + [([True] * 5, [])]
    assert fitness(Rule((("a",),)), cells) == fitness(Rule((("a",),)), _cells(30, 100, 20, 400))


def test_unknown_atom_does_not_become_false():
    """모르는 걸 False 로 세면 '안 걸림' 이 되어 안전해 보인다."""
    r = Rule((("결손금", "영업CF"),))
    assert r.fires({"결손금": True, "영업CF": True}) is True
    assert r.fires({"결손금": True, "영업CF": False}) is False
    assert r.fires({"결손금": True, "영업CF": None}) is None


def test_or_group_fires_even_if_another_group_is_unknown():
    r = Rule((("a",), ("b",)))
    assert r.fires({"a": True, "b": None}) is True     # 한쪽이 확실히 참이면 참
    assert r.fires({"a": False, "b": None}) is None    # 남은 쪽을 모르면 모른다


def test_normalize_kills_duplicate_faces_of_the_same_rule():
    """같은 규칙이 다른 얼굴로 번식하면 개체군이 한 규칙으로 채워진다."""
    rng = random.Random(0)
    r = mutate(Rule((("a", "a", "b"),)), ["a", "b"], rng)
    for g in r.groups:
        assert len(set(g)) == len(g)


def test_mutation_keeps_rules_readable():
    rng = random.Random(1)
    r = random_rule(["a", "b", "c", "d"], rng)
    for _ in range(200):
        r = mutate(r, ["a", "b", "c", "d"], rng)
        assert len(r.groups) <= 2 and all(1 <= len(g) <= 3 for g in r.groups)


def test_crossover_takes_one_group_from_each_parent():
    rng = random.Random(2)
    child = crossover(Rule((("a",),)), Rule((("b",),)), rng)
    assert {a for g in child.groups for a in g} <= {"a", "b"}


def test_or_order_does_not_create_a_second_identity():
    """`A OR B` 와 `B OR A` 가 다른 개체면 개체군이 같은 규칙으로 채워진다."""
    from dartweave.signal.evolve import _normalize

    assert _normalize([["a"], ["b"]]) == _normalize([["b"], ["a"]])
    assert _normalize([["a", "b"], ["c"]]) == _normalize([["c"], ["b", "a"]])
