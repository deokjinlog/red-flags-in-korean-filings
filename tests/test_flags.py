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


# --- 공정위 공시(J)에서 오는 신호 ---------------------------------------------

from dartweave.screen.flags import internal_trade, related_party_funding  # noqa: E402

FUNDING = [("20240115", "특수관계인으로부터자금차입"),
           ("20240220", "특수관계인에대한자금대여")]
TRADE = [(f"2024{m:02d}01", "동일인등출자계열회사와의상품ㆍ용역거래") for m in (1, 2, 3)]


def test_related_party_funding_is_flagged_with_dates():
    f = related_party_funding(FUNDING)
    assert f and f.kind == "특수관계인 자금거래"
    assert "20240220 특수관계인에대한자금대여" in f.evidence


def test_unrelated_reports_do_not_fire():
    assert related_party_funding([("20240101", "임원의변동")]) is None


def test_internal_trade_needs_more_than_one():
    """한두 건은 정상 영업이다 — 임계를 안 두면 거의 모든 계열사가 걸린다."""
    assert internal_trade(TRADE[:2]) is None
    assert internal_trade(TRADE) is not None


def test_internal_trade_threshold_is_visible_in_the_summary():
    """임의값은 숨기지 않는다 — 임계를 보여야 사람이 다시 판단할 수 있다."""
    f = internal_trade(TRADE)
    assert "임계 3건" in f.summary


def test_evidence_is_newest_first():
    f = internal_trade(TRADE)
    assert f.evidence[0].startswith("20240301")


# --- 루브릭: 임의 임계 대신 실측 분포 ------------------------------------------

from dartweave.screen.flags import (  # noqa: E402
    RARITY_COMMON, RARITY_RARE, RARITY_UNCOMMON, funding_rarity, rarity, trade_rarity,
)

# 실측(표본 200사·2024)
DIST_TRADE = {"zero_ratio": 0.845, "median": 0, "p90": 3, "p95": 6, "p99": 18, "max": 26}


def test_rarity_uses_measured_percentiles_not_a_made_up_threshold():
    assert rarity(2, DIST_TRADE)[0] == RARITY_COMMON
    assert rarity(13, DIST_TRADE)[0] == RARITY_UNCOMMON   # 한화 실측값
    assert rarity(25, DIST_TRADE)[0] == RARITY_RARE


def test_rarity_reason_carries_the_percentiles():
    """등급만 주면 못 믿는다 — 어느 분포의 어디인지가 같이 나와야 한다."""
    _, why = rarity(13, DIST_TRADE)
    assert "p95=6" in why and "p99=18" in why and "84%는 0건" in why


def test_without_a_baseline_it_says_so_rather_than_guessing():
    """기준선이 없으면 '흔한지 모른다' 고 적는다. 없는 임계를 지어내지 않는다."""
    f = trade_rarity([("20240101", "동일인등출자계열회사와의상품ㆍ용역거래")])
    assert f and "기준선 없음" in f.summary


def test_no_composite_score_is_produced():
    """항목을 하나로 합치면 '위험도 0.73' 이 되고 아무도 못 믿는다."""
    import dartweave.screen.flags as m
    assert not any(n for n in dir(m) if "score" in n.lower() or "total" in n.lower())


def test_funding_and_trade_are_graded_separately():
    reports = [("20240101", "특수관계인으로부터자금차입"),
               ("20240202", "동일인등출자계열회사와의상품ㆍ용역거래")]
    dist_f = {"zero_ratio": 0.935, "p95": 2, "p99": 5}
    assert funding_rarity(reports, dist_f).kind == "특수관계인 자금거래"
    assert trade_rarity(reports, DIST_TRADE).kind == "계열사 내부거래"


# --- 그래프 검사에도 실측 분포 등급 (전수 1,490개사) ---------------------------

DIST_CYCLES = {"zero_ratio": 0.994, "p90": 0, "p95": 0, "p99": 0, "max": 3}
DIST_NEAR = {"zero_ratio": 0.284, "median": 1, "p90": 5, "p95": 6, "p99": 8, "max": 11}


def test_any_cycle_is_rare_because_99_percent_have_none():
    """실측: 1,490개사 중 99.4% 가 순환출자 고리 0건. 걸리면 그것만으로 드물다."""
    from dartweave.screen.flags import circular_holdings
    edges = [("a", "b", R), ("b", "c", R), ("c", "a", R)]
    f = circular_holdings(edges, "a", name=name, dist=DIST_CYCLES)
    assert f.summary.startswith(RARITY_RARE)


def test_common_chokepoint_proximity_is_labelled_common():
    """실측: 71.6% 가 2홉 안에 공동의존점을 갖는다.

    등급 없이 '걸림' 만 표시하면 회사 10곳 중 7곳에 경고가 붙는다 — 정의상 소음이다.
    """
    from dartweave.screen.flags import near_chokepoint
    edges = [("a", "h", R)]
    f = near_chokepoint(edges, "a", {"h": 3}, name=name, dist=DIST_NEAR)
    assert f.summary.startswith(RARITY_COMMON)


def test_many_chokepoints_is_still_flagged_as_rare():
    from dartweave.screen.flags import near_chokepoint
    edges = [("a", f"h{i}", R) for i in range(9)]
    f = near_chokepoint(edges, "a", {f"h{i}": i + 1 for i in range(9)},
                        name=name, dist=DIST_NEAR)
    assert f.summary.startswith(RARITY_RARE)


def test_graph_baseline_flows_through_screen():
    edges = [("a", "b", R), ("b", "c", R), ("c", "a", R)]
    flags = screen(edges, "a", name=name, baseline={"cycles": DIST_CYCLES})
    assert any(f.summary.startswith(RARITY_RARE) for f in flags)


def test_chokepoint_flag_states_it_is_not_a_risk_signal():
    """신호 검정 결과를 항목에 박아둔다.

    검정 없이 '이상 신호' 라고 부르면 사용자가 위험으로 읽는다. 실측은 반대였다 —
    공동의존점에서 먼 회사가 부실률 2배(p=0.0007).
    """
    from dartweave.screen.flags import near_chokepoint
    edges = [("a", "h", R)]
    f = near_chokepoint(edges, "a", {"h": 3}, name=name)
    assert "부실과 반대 방향" in f.summary


# --- 검정 상태를 항목마다 달고 다닌다 ------------------------------------------

from dartweave.screen.flags import VERIFICATION, verification_of  # noqa: E402


def test_every_check_kind_has_a_verification_entry():
    """검사를 추가하면서 검정 상태를 안 적으면 사용자가 '확인된 위험' 으로 읽는다."""
    kinds = {"상호 지분 보유", "순환출자", "공동의존점 근접", "계열 경계 초과",
             "특수관계인 자금거래", "계열사 내부거래", "대기업집단과의 거리"}
    assert kinds <= set(VERIFICATION)


def test_unknown_kind_defaults_to_unverified():
    """모르는 항목을 조용히 통과시키지 않는다 — 기본값이 '미검정' 이다."""
    assert "미검정" in verification_of("새로 만든 검사")


def test_screen_attaches_verification_to_evidence():
    edges = [("a", "b", R), ("b", "a", R)]
    f = screen(edges, "a", name=name)[0]
    assert any("미검정" in line for line in f.evidence)


def test_chokepoint_carries_the_measured_reversal():
    """반대 방향으로 확인된 건 '미검정' 이 아니라 그 결과를 적는다."""
    v = verification_of("공동의존점 근접")
    assert "반대 방향" in v and "미검정" not in v


def test_conglomerate_distance_verification_is_recorded():
    """처음으로 검정을 통과한 신호 — 방향까지 적어둔다.

    고립 6.8% vs 나머지 2.6% 인데, 자산총계로 규모를 통제하면 ×1.69 (p=0.021) 로 준다.
    겉보기 배율을 그대로 실으면 규모 차이를 신호로 파는 셈이라 통제 후 값을 싣는다.
    걸리는 건 '소속' 이 아니라 '고립' 이다 — 이름만 보고 반대로 읽으면 안 된다.
    """
    v = verification_of("대기업집단과의 거리")
    assert "×1.69" in v and "미검정" not in v


def test_conglomerate_member_is_not_flagged():
    """소속은 가장 안전한 쪽이다 — 경고를 달면 안 된다."""
    from dartweave.screen.flags import conglomerate_distance
    edges = [("a", "b", R)]
    assert conglomerate_distance(edges, "a", {"a", "b"}, name=name) is None


def test_linked_non_member_says_it_is_linked():
    from dartweave.screen.flags import conglomerate_distance
    edges = [("a", "b", R)]
    f = conglomerate_distance(edges, "a", {"b"}, name=name)
    assert f and "연결" in f.summary and "나회사" in f.evidence


def test_isolated_company_is_the_one_that_fires():
    from dartweave.screen.flags import conglomerate_distance
    edges = [("a", "b", R)]
    f = conglomerate_distance(edges, "a", {"zzz"}, name=name)
    assert f and "고립" in f.summary and "×1.69" in f.summary


def test_no_member_list_means_no_judgement():
    """명단이 없으면 판정하지 않는다 — 모르는 걸 '고립' 으로 세면 전부 걸린다."""
    from dartweave.screen.flags import conglomerate_distance
    assert conglomerate_distance([("a", "b", R)], "a", set(), name=name) is None
