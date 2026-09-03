"""지배구조 이상 신호 검출.

이 층의 계약은 하나다 — **근거 없는 경고를 만들지 않는다.** 경고만 늘어놓으면
소음이 되고, 소음은 실무에서 무시된다. 그래서 `Flag` 는 `evidence` 없이 생성 자체가
안 되게 막아뒀고, 아래 테스트가 그걸 고정한다.
"""
from pathlib import Path

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

    통제 전 ×2.61 인데 규모·업종 통제를 촘촘히 할수록 ×1.29 까지 줄고 유의성이 사라진다.
    유의해지는 설정을 골라 쓰면 파라미터 고르기라 채택하지 않는다 — 그 사실을 싣는다.
    걸리는 건 '소속' 이 아니라 '고립' 이다 — 이름만 보고 반대로 읽으면 안 된다.
    """
    v = verification_of("대기업집단과의 거리")
    assert "채택 안 함" in v and "×1.29" in v


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
    assert f and "고립" in f.summary and "사라진다" in f.summary


def test_no_member_list_means_no_judgement():
    """명단이 없으면 판정하지 않는다 — 모르는 걸 '고립' 으로 세면 전부 걸린다."""
    from dartweave.screen.flags import conglomerate_distance
    assert conglomerate_distance([("a", "b", R)], "a", set(), name=name) is None


def test_adopted_financial_signals_say_so():
    """검정을 통과한 둘 — 검정 상태에 '채택' 이 박혀 있어야 한다."""
    for kind, ratio in (("결손금", "×9.47"), ("영업손실", "×8.30"), ("당기순손실", "×11.71")):
        v = verification_of(kind)
        assert "채택" in v and "미검정" not in v and ratio in v
    # 약한 쪽도 is_adopted 로는 채택이어야 한다 — 검색이 이걸로 순서를 가른다.
    from dartweave.screen.flags import is_adopted
    assert all(is_adopted(k) for k in ("결손금", "영업손실", "당기순손실"))


def test_accumulated_deficit_fires_only_on_negative_retained_earnings():
    from dartweave.screen.flags import accumulated_deficit

    assert accumulated_deficit(-1_200_000_000_000, year="2023") is not None
    assert accumulated_deficit(500_000_000_000) is None


def test_missing_financials_are_not_counted_as_healthy():
    """재무를 못 받은 걸 '흑자' 로 세면 안 된다 — 모르는 건 판정하지 않는다."""
    from dartweave.screen.flags import accumulated_deficit

    assert accumulated_deficit(None) is None


def test_deficit_summary_carries_the_measured_rate():
    from dartweave.screen.flags import accumulated_deficit

    f = accumulated_deficit(-1_000_000_000_000, year="2022")
    assert f and "2022년" in f.summary and "10,000억" in f.summary
    assert any("4.2~7.4%" in e for e in f.evidence)


def test_operating_loss_fires_only_on_negative_operating_income():
    from dartweave.screen.flags import operating_loss

    assert operating_loss(-50_000_000_000, year="2022") is not None
    assert operating_loss(50_000_000_000) is None
    assert operating_loss(None) is None       # 모르는 건 '흑자' 가 아니다


def test_deficit_and_operating_loss_are_separate_checks():
    """누적(결손금)과 당해(영업손실)는 겹치지만 같지 않다 — 따로 걸려야 한다."""
    from dartweave.screen.flags import accumulated_deficit, operating_loss

    assert accumulated_deficit(1_000_000_000) is None    # 누적은 흑자인데
    assert operating_loss(-1_000_000_000) is not None    # 올해만 적자


def test_is_adopted_does_not_leak_withdrawn_checks():
    """'채택 안 함' 이 '채택' 으로 새면 철회한 신호를 통과한 것처럼 판다."""
    from dartweave.screen.flags import is_adopted

    assert is_adopted("결손금") and is_adopted("영업손실")
    assert not is_adopted("대기업집단과의 거리")     # 철회
    assert not is_adopted("공동의존점 근접")         # 반대 방향
    assert not is_adopted("순환출자")                # 미검정
    assert not is_adopted("있지도 않은 검사")


def test_signal_strengths_are_graded_not_lumped():
    """신호마다 근거 강도가 다르다 — 같은 문구로 팔면 안 된다."""
    assert "Bonferroni 통과" in verification_of("결손금")
    # 방향은 둘로 갈린다. 이익잉여금은 채택, 영업이익은 반려 — 묶으면 안 되는 이유가
    # 검정 상태에 적혀 있어야 한다.
    up = verification_of("이익잉여금 3년 악화")
    down = verification_of("영업이익 3년 악화")
    assert "채택" in up and "가장 크게 가른다" in up
    assert down.lstrip().startswith("**채택 안 함") and "개선 쪽이 오히려 높다" in down


def test_base_labels_change_is_recorded_not_hidden():
    """답안지에서 영업정지를 뺀 사실이 표에 남아 있어야 한다 — 숫자가 다 바뀌었다."""
    from dartweave.screen import flags
    src = Path(flags.__file__).read_text(encoding="utf-8")
    assert "영업정지를 뺀 뒤" in src and "810→526" in src


def test_weak_adoption_still_counts_as_adopted():
    """'채택(약)' 은 채택이다 — 약한 것과 아닌 것은 다르다."""
    from dartweave.screen.flags import is_adopted

    assert is_adopted("영업손실")
    assert not is_adopted("대기업집단과의 거리")


def test_adopted_signals_carry_their_false_positive_burden():
    """×3.7 을 '망한다' 로 읽지 않게, 걸린 것 대부분이 무사하다는 사실을 같이 낸다."""
    from dartweave.screen.flags import accumulated_deficit, operating_loss

    from dartweave.screen.flags import net_loss

    flags = [accumulated_deficit(-1_000_000_000), operating_loss(-1_000_000_000),
             net_loss(-1_000_000_000)]
    for f in flags:
        assert any("아무 일도 없었다" in e for e in f.evidence)
        assert any("실제 부실의" in e for e in f.evidence)


def test_net_loss_is_the_widest_of_the_three():
    """당기순손실은 셋 중 가장 넓게 건다 — 재현율 높고 정밀도 낮다."""
    from dartweave.screen.flags import net_loss

    assert net_loss(-30_000_000_000, year="2022") is not None
    assert net_loss(30_000_000_000) is None
    assert net_loss(None) is None
    assert "33~37%가 여기 걸리고" in " ".join(net_loss(-1).evidence)


def test_net_loss_records_that_an_earlier_verdict_was_wrong():
    """표본을 그래프로 좁혀놔서 '시점에 따라 갈린다' 고 잘못 뺐던 신호다."""
    from dartweave.screen.flags import net_loss

    assert "그 판정이 틀렸다" in (net_loss.__doc__ or "")


def test_cashflow_and_coverage_checks_need_their_inputs():
    """현금흐름·이자비용이 없으면 판정하지 않는다 — 없는 걸 '양호' 로 세지 않는다."""
    from dartweave.screen.flags import (
        interest_coverage_below_one,
        negative_operating_cashflow,
    )

    assert negative_operating_cashflow(None) is None
    assert negative_operating_cashflow(5_000_000_000) is None
    assert negative_operating_cashflow(-5_000_000_000, year="2023") is not None

    assert interest_coverage_below_one(None, 100.0) is None
    assert interest_coverage_below_one(100.0, None) is None
    assert interest_coverage_below_one(100.0, 0.0) is None      # 0 으로 나누면 무한대


def test_interest_coverage_fires_on_profitable_but_overleveraged():
    """흑자여도 이자가 더 크면 걸린다 — 부채 많은 흑자 기업이 그렇다."""
    from dartweave.screen.flags import interest_coverage_below_one

    f = interest_coverage_below_one(30_000_000_000, 70_000_000_000, year="2023")
    assert f and "0.43배" in f.summary
    assert interest_coverage_below_one(70_000_000_000, 30_000_000_000) is None


def test_negative_coverage_ratio_is_not_printed_as_a_number():
    """영업손실이면 배율이 음수다 — '-8.40배' 는 여유가 있는 것처럼 오독된다."""
    from dartweave.screen.flags import interest_coverage_below_one

    loss = interest_coverage_below_one(-78_200_000_000, 9_300_000_000, year="2023")
    assert loss and "배" not in loss.summary.split("—")[1].split("(")[0]
    assert "영업손실이라" in loss.summary


def test_flag_count_bands_are_measured_not_invented():
    """개수 구간의 부실률은 실측값이다 — 임의 등급이 아니다."""
    from dartweave.screen.flags import ADOPTED_KINDS, flag_count_summary

    assert len(ADOPTED_KINDS) == 5
    zero = flag_count_summary(0, 5)
    many = flag_count_summary(6, 5)
    assert "0개" in zero and "0.00~0.20%" in zero
    assert "5개 이상" in many and "5.54~10.18%" in many


def test_direction_outranks_count_in_the_middle_bands():
    """개수만으로 순서를 매기면 틀린다 — 3개+악화(8.1%)가 5개+악화아님(5.9%)보다 높다."""
    from dartweave.screen.flags import direction_split

    assert "8.1%" in direction_split(3, True)
    assert "0.0%" in direction_split(4, False)
    # 3년치가 없으면 '악화 아님' 이 아니라 '모른다' 다.
    unknown = direction_split(4, None)
    assert "판정하지 못했습니다" in unknown and "덜 아는 것" in unknown
    # 표본이 얇은 구간은 없는 정밀도를 만들지 않는다.
    assert direction_split(1, True) == ""


def test_flag_count_says_when_it_could_not_judge():
    """재무를 못 받아 못 센 신호가 있으면 '0개' 가 안전을 뜻하지 않는다."""
    from dartweave.screen.flags import flag_count_summary

    assert "판정 못 함" in flag_count_summary(0, 3)
    assert "판정 못 함" not in flag_count_summary(0, 5)


def test_audit_layer_narrows_within_the_same_count():
    """같은 5개 걸림 안에서 감사 경고 유무가 5.2% 와 43.5% 로 가른다."""
    from dartweave.screen.flags import audit_split

    warned = audit_split(5, "concern", "2023")
    clean = audit_split(5, "none", "2023")
    assert "43.5%" in warned and "2023 사업연도" in warned
    assert "5.2%" in clean and "8분의 1" in clean
    # 둘 다 깨끗하면 실측 부실 0건이었다 — 그 사실을 그대로 낸다.
    assert "0건" in audit_split(0, "none", "2023")


def test_missing_audit_is_not_absence_of_warning():
    """감사의견을 못 받은 것과 경고가 없는 것은 다르다 — 섞으면 안전해 보인다."""
    from dartweave.screen.flags import audit_split

    unknown = audit_split(5, None)
    assert "모릅니다" in unknown and "덜 아는 것" in unknown
    # 걸린 개수와 무관하게 '5개 걸린' 이라고 말하면 안 된다.
    assert "같은 5개 걸린" not in audit_split(0, None)


def test_audit_year_is_stamped_because_it_lags_the_financials():
    """감사의견 연도가 재무와 다를 수 있다 — 안 밝히면 같은 해로 읽힌다."""
    from dartweave.screen.flags import audit_split

    assert "2023 사업연도" in audit_split(3, "concern", "2023")


def test_audit_says_only_one_base_date_produced_a_verdict():
    """가장 강한 값(x12.28)이지만 두 시점 중 하나만 판정났다 — 둘 다 말해야 한다."""
    from dartweave.screen import flags

    warned = flags.audit_split(5, "concern", "2023")
    assert "×12.28" in warned and "한 시점만 판정" in warned
    src = Path(flags.__file__).read_text(encoding="utf-8")
    # 왜 채택 신호로 안 올렸는지가 코드에 남아 있어야 한다.
    assert "신호군 부실 8건" in src and "기준을 느슨하게" in src


def test_korean_particle_agrees_with_the_final_jamo():
    """'계속기업 경고이 있습니다' 같은 게 나오면 안 된다."""
    from dartweave.screen.flags import _subject

    assert _subject("계속기업 경고") == "계속기업 경고가"
    assert _subject("의견거절·한정") == "의견거절·한정이"
    assert _subject("CB") == "CB가"          # 한글이 아니면 기본형


def test_bad_disclosure_narrows_but_never_stands_alone():
    """재무 신호가 없으면 공시 행태만으로는 예고되지 않는다 — 실측 부실 0건이었다."""
    from dartweave.screen.flags import disclosure_split

    strong = disclosure_split(5, 2)
    assert "29.9%" in strong and "5.2%" in strong
    alone = disclosure_split(2, 1)
    assert "0건" in alone and "이것만으로 예고되지 않습니다" in alone
    # 명단을 못 받은 것과 지정이 없는 것은 다르다.
    assert disclosure_split(5, None) == ""
    assert disclosure_split(0, 0) and "없습니다" in disclosure_split(0, 0)


def test_penalty_line_is_the_rulebook_not_ours():
    """8점은 코스닥 공시규정의 관리종목 지정선이다 — 우리가 고른 임계가 아니다."""
    from dartweave.screen.flags import PENALTY_LINE, penalty_band

    assert PENALTY_LINE == 8.0
    high = penalty_band(9.0)
    assert "8점 이상" in high and "관리종목 지정선" in high
    assert "우리가 고른 값이 아니고" in high
    low = penalty_band(2.5)
    assert "0~4점" in low and "관리종목 지정선" not in low


def test_penalty_says_nothing_when_there_is_nothing_to_say():
    """지정된 적이 없으면 벌점 문장을 내지 않는다 — 같은 사실을 두 번 말하지 않는다."""
    from dartweave.screen.flags import penalty_band

    assert penalty_band(0.0) == ""
    assert penalty_band(None) == ""


def test_substituted_penalty_is_not_restored_into_the_signal():
    """대체부과 벌점을 복원해 쓰면 덜 위험한 회사를 위험 쪽으로 올린다."""
    from pathlib import Path

    from dartweave.screen import flags

    src = Path(flags.__file__).read_text(encoding="utf-8")
    # 왜 복원값을 안 쓰는지가 코드에 남아 있어야 한다 — 실측이 근거다.
    assert "복원해서 쓰면 안 된다" in src
    assert "대체부과만 있던 회사" in src and "×3.9" in src
