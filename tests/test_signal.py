"""신호 검정 — 우연과 구분되는가.

층1이 모듈러리티에 절대 기준을 안 쓴 것과 같은 규율이다. "신호군 부실률 12%" 는
그 자체로 아무 뜻이 없다 — 비신호군이 몇 %인지가 있어야 판단이 된다.
"""
from dartweave.signal.test import MIN_POSITIVES, Verdict, permutation_test


def _grp(events, n):
    return [True] * events + [False] * (n - events)


def test_clear_difference_is_supported():
    r = permutation_test(_grp(30, 100), _grp(10, 100), runs=500)
    assert r.verdict is Verdict.SUPPORTED
    assert r.p_value < 0.05 and round(r.lift, 2) == 3.0


def test_no_real_difference_is_not_supported():
    """차이가 없으면 '없다' 고 말한다 — 억지로 신호를 만들지 않는다."""
    r = permutation_test(_grp(25, 100), _grp(24, 100), runs=500)
    assert r.verdict is Verdict.NO_DIFFERENCE


def test_too_few_positives_refuses_to_judge():
    """부실 사례가 적으면 판정 자체를 안 한다 — 우리 실측이 연 90건이라 흔한 상황이다."""
    r = permutation_test(_grp(MIN_POSITIVES - 1, 100), _grp(2, 100), runs=500)
    assert r.verdict is Verdict.TOO_FEW and r.p_value is None


def test_lift_is_reported_alongside_the_rate():
    """비율만 보면 기저율을 못 본다 — 12% 가 높은지는 대조군을 봐야 안다."""
    r = permutation_test(_grp(40, 100), _grp(20, 100), runs=500)
    assert round(r.lift, 2) == 2.0
    assert "×2.00" in r.explain()


def test_p_value_never_reaches_zero():
    """p=0 은 '불가능' 이 아니라 '못 봤다' 다. +1 보정으로 0 을 막는다."""
    r = permutation_test(_grp(90, 100), _grp(1, 100), runs=200)
    assert r.p_value > 0


def test_result_is_reproducible():
    a = permutation_test(_grp(30, 100), _grp(10, 100), runs=300, seed=7)
    b = permutation_test(_grp(30, 100), _grp(10, 100), runs=300, seed=7)
    assert a.p_value == b.p_value


def test_all_three_verdicts_are_the_same_type():
    """AC-10 과 같은 규율 — '판정 불가' 가 예외가 아니다."""
    rs = [permutation_test(_grp(30, 100), _grp(10, 100), runs=200),
          permutation_test(_grp(25, 100), _grp(24, 100), runs=200),
          permutation_test(_grp(3, 100), _grp(2, 100), runs=200)]
    assert all(isinstance(r.verdict, Verdict) for r in rs)
    assert len({r.verdict for r in rs}) == 3


def test_repeated_observations_inflate_significance():
    """실측 사고 재현 — 같은 회사를 여러 번 세면 p 가 부풀려진다.

    순환출자 검정에서 기업-연도로 세니 ×4.18 · p=0.0005 로 유의했는데,
    회사당 한 번만 세니 신호군 부실이 10건뿐이라 TOO_FEW 였다.
    같은 관측을 4배로 복제하면 차이가 그대로여도 p 가 극적으로 낮아진다.
    """
    sig, ctl = _grp(6, 30), _grp(10, 300)          # 회사 단위 — 양성 6건
    once = permutation_test(sig, ctl, runs=500)
    assert once.verdict is Verdict.TOO_FEW          # 20건 미만이라 판정 거부

    four = permutation_test(sig * 4, ctl * 4, runs=500)   # 같은 걸 4번 복제
    assert four.verdict is Verdict.SUPPORTED        # 비율은 같은데 유의해진다
    assert abs(four.signal_rate - once.signal_rate) < 1e-9


def test_min_positives_guard_is_what_caught_it():
    """복제로 부풀린 결과를 막은 건 MIN_POSITIVES 가드였다."""
    assert permutation_test(_grp(19, 100), _grp(5, 500), runs=200).verdict is Verdict.TOO_FEW
    assert permutation_test(_grp(20, 100), _grp(5, 500), runs=200).verdict is not Verdict.TOO_FEW
