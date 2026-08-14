from dartweave.structure.verdict import Verdict, decide


def test_stable_and_significant_is_accepted():
    v = decide(z=190.0, effect_size=0.13, sweep_holds=True, has_outlier=True)
    assert v is Verdict.ACCEPTED


def test_flat_metrics_yield_no_conclusion():
    """지표가 평평하면 '집중이 관측되지 않는다' 가 결론이다 — 이것도 발견이다."""
    v = decide(z=190.0, effect_size=0.13, sweep_holds=True, has_outlier=False)
    assert v is Verdict.NO_CONCLUSION


def test_unstable_sweep_is_parameter_dependent():
    v = decide(z=190.0, effect_size=0.13, sweep_holds=False, has_outlier=True)
    assert v is Verdict.PARAMETER_DEPENDENT


def test_weak_structure_yields_no_conclusion():
    v = decide(z=1.2, effect_size=0.004, sweep_holds=True, has_outlier=True)
    assert v is Verdict.NO_CONCLUSION


def test_er_noise_level_effect_does_not_pass():
    """무구조 ER 그래프 실측 상한(+0.02)이 임계를 넘으면 안 된다.

    z 는 크게 뜰 수 있다(귀무 sd 가 0.0005 수준) — 그래서 효과크기가 잡는다.
    """
    v = decide(z=40.0, effect_size=0.02, sweep_holds=True, has_outlier=True)
    assert v is Verdict.NO_CONCLUSION


def test_measured_real_signal_passes():
    """실측 기준선(+0.1305 · z=193.8)은 통과해야 한다 — 임계가 과하면 안 된다."""
    v = decide(z=193.8, effect_size=0.1305, sweep_holds=True, has_outlier=True)
    assert v is Verdict.ACCEPTED


def test_all_states_are_the_same_type():
    """AC-10 — 세 상태가 동등한 반환값. '결론 없음' 이 예외가 아니다."""
    results = [
        decide(z=190.0, effect_size=0.13, sweep_holds=True, has_outlier=True),
        decide(z=190.0, effect_size=0.13, sweep_holds=True, has_outlier=False),
        decide(z=190.0, effect_size=0.13, sweep_holds=False, has_outlier=True),
    ]
    assert all(isinstance(r, Verdict) for r in results)
    assert len(set(results)) == 3
