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
