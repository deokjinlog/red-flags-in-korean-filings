"""지배구조 이상 신호 검출.

이 층의 계약은 하나다 — **근거 없는 경고를 만들지 않는다.** 경고만 늘어놓으면
소음이 되고, 소음은 실무에서 무시된다. 그래서 `Flag` 는 `evidence` 없이 생성 자체가
안 되게 막아뒀고, 아래 테스트가 그걸 고정한다.
"""
import pytest

from dartweave.screen.flags import (
    Flag,
    circular_holdings,
    crosses_group_boundary,
    hops_to,
    mutual_holdings,
    near_chokepoint,
    screen,
)

R = "MAJOR_SHAREHOLDER_OF"
NM = {"a": "가회사", "b": "나회사", "c": "다회사", "d": "라회사", "h": "공제조합"}
name = lambda c: NM.get(c, c)  # noqa: E731


def test_flag_without_evidence_is_rejected():
    """근거 없는 경고는 만들 수조차 없어야 한다."""
    with pytest.raises(ValueError):
        Flag(kind="아무거나", summary="걸림", evidence=[])


def test_mutual_holding_is_detected():
    """실측: 케이씨씨와 HD한국조선해양이 서로를 보유한다."""
    edges = [("a", "b", R), ("b", "a", R)]
    f = mutual_holdings(edges, "a", name=name)
    assert f and f.kind == "상호 지분 보유"
    assert "가회사 ↔ 나회사 · 지분율 미상" in f.evidence


def test_trivial_stake_is_not_flagged():
    """회귀 방지 — 실측에서 **0.06%** 보유를 '상호출자' 로 경고한 사고가 있었다.

    지분율을 알면 임계 미만은 걸러야 한다. 안 그러면 경고가 소음이 되고,
    소음이 되면 실무에서 통째로 무시된다.
    """
    edges = [("a", "b", R), ("b", "a", R)]
    assert mutual_holdings(edges, "a", name=name,
                           share_of={("b", "a"): 0.06}) is None


def test_meaningful_stake_is_flagged_with_its_value():
    edges = [("a", "b", R), ("b", "a", R)]
    f = mutual_holdings(edges, "a", name=name, share_of={("b", "a"): 12.5})
    assert f and "최대 12.50%" in f.evidence[0]


def test_unknown_stake_says_so_rather_than_guessing():
    """지분율을 모르면 '미상' 이라고 적는다 — 모르는 걸 통과나 탈락으로 치지 않는다."""
    edges = [("a", "b", R), ("b", "a", R)]
    f = mutual_holdings(edges, "a", name=name, share_of={})
    assert f and "지분율 미상" in f.evidence[0]


def test_regulatory_term_is_not_used_as_the_label():
    """'상호출자' 는 상호출자제한기업집단의 계열회사 간에 쓰는 규제 용어다.

    단순 지분 보유에 그 이름을 붙이면 없는 규제 위반을 있는 것처럼 읽힌다.
    """
    edges = [("a", "b", R), ("b", "a", R)]
    f = mutual_holdings(edges, "a", name=name)
    assert f.kind != "상호출자"
    assert "규제상 상호출자와는 별개" in f.summary


def test_one_way_holding_is_not_mutual():
    assert mutual_holdings([("a", "b", R)], "a", name=name) is None


def test_circular_holding_is_detected():
    edges = [("a", "b", R), ("b", "c", R), ("c", "a", R)]
    f = circular_holdings(edges, "a", name=name)
    assert f and f.kind == "순환출자"
    assert "가회사 → 나회사 → 다회사 → 가회사" in f.evidence


def test_mutual_holding_is_not_counted_as_circular():
    """상호출자(길이 2)를 순환출자로도 세면 무엇이 걸렸는지가 뭉개진다."""
    edges = [("a", "b", R), ("b", "a", R)]
    assert circular_holdings(edges, "a", name=name) is None


def test_cycle_not_through_me_is_not_mine():
    """B→C→D→B 고리가 있어도 내가 안 끼면 내 순환출자가 아니다."""
    edges = [("a", "b", R), ("b", "c", R), ("c", "d", R), ("d", "b", R)]
    assert circular_holdings(edges, "a", name=name) is None


def test_long_cycle_beyond_limit_is_ignored():
    chain = [(f"n{i}", f"n{i+1}", R) for i in range(8)]
    edges = [("a", "n0", R), *chain, ("n8", "a", R)]
    assert circular_holdings(edges, "a", name=name, max_len=4) is None


def test_hops_ignore_edge_direction():
    """위험은 출자 방향을 안 가린다 — 내가 소유하든 소유당하든 얽힌 건 같다."""
    edges = [("h", "a", R)]                       # 조합이 나를 소유
    assert hops_to(edges, "a", {"h"}, max_hops=2) == {"h": 1}


def test_near_chokepoint_reports_distance_and_rank():
    edges = [("a", "b", R), ("b", "h", R)]
    f = near_chokepoint(edges, "a", {"h": 3}, name=name, max_hops=2)
    assert f and "공제조합 — 2홉 · 매개중심성 3위" in f.evidence


def test_far_chokepoint_is_not_flagged():
    edges = [("a", "b", R), ("b", "c", R), ("c", "h", R)]
    assert near_chokepoint(edges, "a", {"h": 3}, name=name, max_hops=2) is None


def test_group_boundary_crossing_is_detected():
    """실측: 현대자동차→HD현대, 케이씨씨→현대모비스 — 공정위 지정으로는 다른 집단."""
    edges = [("a", "b", R)]
    f = crosses_group_boundary(edges, "a", {"a": "가그룹", "b": "나그룹"}, name=name)
    assert f and "나회사 (나그룹)" in f.evidence


def test_same_group_is_not_a_crossing():
    edges = [("a", "b", R)]
    assert crosses_group_boundary(edges, "a", {"a": "가그룹", "b": "가그룹"},
                                  name=name) is None


def test_unlabeled_counterpart_is_not_judged():
    """라벨이 없으면 판정하지 않는다 — 모르는 걸 '넘었다' 로 세면 거짓 경고가 된다."""
    edges = [("a", "b", R)]
    assert crosses_group_boundary(edges, "a", {"a": "가그룹"}, name=name) is None


def test_screen_returns_only_what_actually_fired():
    edges = [("a", "b", R), ("b", "a", R)]
    kinds = [f.kind for f in screen(edges, "a", name=name)]
    assert kinds == ["상호 지분 보유"]


def test_empty_result_means_not_caught_by_these_checks():
    """빈 목록은 '이상 없음' 이 아니다 — 검사 범위 밖은 이 함수가 모른다."""
    assert screen([("a", "b", R)], "a", name=name) == []


def test_every_flag_carries_evidence():
    edges = [("a", "b", R), ("b", "a", R), ("b", "c", R), ("c", "a", R), ("c", "h", R)]
    flags = screen(edges, "a", name=name, chokepoints={"h": 3},
                   group_of={"a": "가그룹", "b": "나그룹"})
    assert len(flags) >= 3
    assert all(f.evidence for f in flags)
