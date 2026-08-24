"""재무 신호 정의 — 스크립트지만 정의가 틀리면 모든 검정이 같이 틀린다."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from test_financial_signals import features, interest_cost  # noqa: E402


def _acc(**kw):
    base = {"이익잉여금": 1.0, "영업이익": 1.0, "자본총계": 10.0, "자본금": 5.0,
            "부채총계": 1.0, "당기순이익(손실)": 1.0, "매출액": 100.0}
    base.update(kw)
    return base


def test_interest_cost_prefers_cash_paid_over_finance_costs():
    """금융원가에는 외환차손·파생평가손실이 섞인다 — 실제 나간 현금이 먼저다."""
    assert interest_cost({"금융원가": 9.0, "이자의지급": 4.0}) == 4.0
    assert interest_cost({"금융원가": 9.0, "이자비용": 6.0}) == 6.0
    assert interest_cost({"금융원가": 9.0}) == 9.0


def test_interest_cost_ignores_zero_and_missing():
    """이자비용 0 을 그대로 쓰면 배율이 무한대가 되어 판정이 뒤집힌다."""
    assert interest_cost({"이자의지급": 0.0, "이자비용": 5.0}) == 5.0
    assert interest_cost({}) is None


def test_missing_cashflow_is_unknown_not_healthy():
    """현금흐름을 못 받은 걸 '양수' 로 세면 안 된다."""
    f = features(_acc(), {}, {})
    assert f["영업현금흐름 음수"] is None
    assert f["이자보상배율 1 미만"] is None


def test_operating_loss_always_fails_interest_coverage():
    """영업손실이면 이자를 갚을 재원이 정의상 없다."""
    f = features(_acc(영업이익=-5.0), {}, {"이자의지급": 1.0})
    assert f["이자보상배율 1 미만"] is True


def test_interest_coverage_threshold_is_one_times():
    f_low = features(_acc(영업이익=3.0), {}, {"이자의지급": 7.0})
    f_high = features(_acc(영업이익=7.0), {}, {"이자의지급": 3.0})
    assert f_low["이자보상배율 1 미만"] is True
    assert f_high["이자보상배율 1 미만"] is False


def test_negative_operating_cashflow_is_flagged():
    assert features(_acc(), {}, {"영업활동현금흐름": -3.0})["영업현금흐름 음수"] is True
    assert features(_acc(), {}, {"영업활동현금흐름": 3.0})["영업현금흐름 음수"] is False


def test_sales_drop_needs_a_previous_year():
    """전년이 없으면 '감소' 를 판정할 수 없다 — 없는 걸 '감소 아님' 으로 세지 않는다."""
    assert features(_acc(), {}, {})["매출 감소"] is None
    assert features(_acc(매출액=50.0), _acc(매출액=100.0), {})["매출 감소"] is True


def test_partial_impairment_excludes_full_impairment():
    """부분자본잠식과 완전자본잠식이 겹치면 같은 회사를 두 번 세게 된다."""
    full = features(_acc(자본총계=-1.0, 자본금=5.0), {}, {})
    assert full["완전자본잠식"] is True and full["부분자본잠식"] is False
    assert full["자본잠식(완전+부분)"] is True


def test_debt_ratio_needs_positive_equity():
    """자본이 0 이하면 부채비율이 정의되지 않는다 — 나누면 부호가 뒤집힌다."""
    assert features(_acc(자본총계=-1.0, 부채총계=100.0), {}, {})["부채비율 200% 초과"] is None
    assert features(_acc(자본총계=10.0, 부채총계=30.0), {}, {})["부채비율 200% 초과"] is True
    assert features(_acc(자본총계=10.0, 부채총계=10.0), {}, {})["부채비율 200% 초과"] is False


def _cf(**kw):
    base = {"영업활동현금흐름": 10.0, "재무활동현금흐름": -5.0, "이자의지급": 1.0}
    base.update(kw)
    return base


def test_profit_without_cash_is_the_textbook_case():
    """순이익은 나는데 영업현금은 나간다 — 가공매출·밀어내기의 전형."""
    f = features(_acc(**{"당기순이익(손실)": 50.0}), {}, _cf(영업활동현금흐름=-20.0))
    assert f["이익-현금 괴리"] is True
    # 둘 다 마이너스면 '괴리' 가 아니라 그냥 적자다
    g = features(_acc(**{"당기순이익(손실)": -50.0}), {}, _cf(영업활동현금흐름=-20.0))
    assert g["이익-현금 괴리"] is False


def test_accrual_ratio_divides_by_assets():
    """규모를 지우지 않으면 큰 회사가 자동으로 상위에 온다."""
    from test_financial_signals import accrual_ratio

    small = accrual_ratio(_acc(자산총계=100.0, **{"당기순이익(손실)": 10.0}), _cf(영업활동현금흐름=0.0))
    big = accrual_ratio(_acc(자산총계=10_000.0, **{"당기순이익(손실)": 100.0}), _cf(영업활동현금흐름=0.0))
    assert small > big                       # 절대액은 big 이 10배인데 비율은 small 이 크다
    assert accrual_ratio(_acc(자산총계=0.0), _cf()) is None      # 0 으로 안 나눈다


def test_financing_lifeline_needs_both_legs():
    """영업에서 나가고 재무로 들어와야 '연명' 이다. 한쪽만으로는 아니다."""
    assert features(_acc(), {}, _cf(영업활동현금흐름=-1.0, 재무활동현금흐름=1.0))["재무CF 연명"] is True
    assert features(_acc(), {}, _cf(영업활동현금흐름=-1.0, 재무활동현금흐름=-1.0))["재무CF 연명"] is False
    assert features(_acc(), {}, _cf(영업활동현금흐름=1.0, 재무활동현금흐름=1.0))["재무CF 연명"] is False


def test_zombie_needs_three_known_years():
    """한 해라도 모르면 '3년 연속' 을 주장할 수 없다."""
    bad = (_acc(영업이익=1.0), _cf(이자의지급=9.0))
    good = (_acc(영업이익=9.0), _cf(이자의지급=1.0))
    assert features(_acc(), {}, _cf(), history=[bad, bad, bad])["이자보상배율<1 3년 연속"] is True
    assert features(_acc(), {}, _cf(), history=[bad, good, bad])["이자보상배율<1 3년 연속"] is False
    assert features(_acc(), {}, _cf(), history=[bad, bad])["이자보상배율<1 3년 연속"] is None
    unknown = (_acc(영업이익=1.0), {})
    assert features(_acc(), {}, _cf(), history=[bad, bad, unknown])["이자보상배율<1 3년 연속"] is None


def test_working_capital_spike_is_relative_to_sales():
    """매출이 같이 늘었으면 급증이 아니다 — 매출 대비로 봐야 한다."""
    acc, prev = _acc(매출액=200.0), _acc(매출액=100.0)
    was = _cf(매출채권=10.0, 재고자산=10.0)
    up = _cf(매출채권=30.0, 재고자산=30.0)          # 운전자본 3배 vs 매출 2배
    flat = _cf(매출채권=15.0, 재고자산=15.0)        # 1.5배 — 매출 증가폭 안
    assert features(acc, prev, up, was)["매출채권+재고 급증"] is True
    assert features(acc, prev, flat, was)["매출채권+재고 급증"] is False


def test_working_capital_reads_the_full_statement_not_key_accounts():
    """실측 사고 — 매출채권을 주요계정에서 찾다가 전 기업이 None 이 되어 0사로 나왔다.

    '해당 기업 0사' 는 '그런 회사가 없다' 가 아니라 '못 읽었다' 였다.
    """
    acc, prev = _acc(매출액=200.0, 매출채권=99.0), _acc(매출액=100.0, 매출채권=1.0)
    # 주요계정 쪽에만 넣으면 판정 불가여야 한다 — 거기 있을 수 없는 값이다.
    assert features(acc, prev, _cf(), _cf())["매출채권+재고 급증"] is None


def test_bond_count_distinguishes_zero_from_unknown():
    """목록을 안 받은 상태의 '0건' 을 '발행 없음' 으로 세면 전 기업이 안전해 보인다."""
    assert features(_acc(), {}, _cf(), bond_count=None)["최근 3년 CB·BW 발행"] is None
    assert features(_acc(), {}, _cf(), bond_count=0)["최근 3년 CB·BW 발행"] is False
    assert features(_acc(), {}, _cf(), bond_count=1)["최근 3년 CB·BW 발행"] is True
    assert features(_acc(), {}, _cf(), bond_count=1)["최근 3년 CB·BW 2회 이상"] is False
    assert features(_acc(), {}, _cf(), bond_count=2)["최근 3년 CB·BW 2회 이상"] is True
