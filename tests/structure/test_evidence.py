import json

from dartweave.structure.evidence import EvidenceBlock, Scope, Thresholds, to_json
from dartweave.structure.metrics import ClusterRow
from dartweave.structure.verdict import Verdict


def _block() -> EvidenceBlock:
    return EvidenceBlock(
        lens="governance",
        include_types=["MAJOR_SHAREHOLDER_OF"],
        objective="modularity",
        resolution=1.0,
        clusters=[ClusterRow(0, 11, 34, 287, 26.1, 0.4)],
        modularity=0.8535,
        null_mean=0.7230,
        null_sd=0.0007,
        null_runs=20,
        null_swaps_failed=0,
        cpm_clusters=52,
        cpm_delta=14,
        sweep_holds=True,
        sweep_ratio=1.12,
        coef_sweep_holds=True,
        coef_sweep_ratio=1.04,
        corporate_resolution_rate=0.60,
        scope=Scope(industry="건설", companies=1490, disclosures=2984,
                    fiscal_year="2024", boundary_ratio=0.0),
        thresholds=Thresholds(0.8, 0.0, 0.05, 3.0, 1.5),
        verdict=Verdict.ACCEPTED,
    )


def test_scope_is_mandatory_and_carries_boundary_ratio():
    """AC-13 + AC-14 가 한 필드에서 만난다."""
    d = json.loads(to_json(_block()))
    assert d["scope"]["boundary_ratio"] == 0.0
    assert d["scope"]["companies"] == 1490
    assert d["scope"]["industry"] == "건설"


def test_thresholds_are_published_not_buried():
    """AC-12 — 통과/반려 사유를 산출물만 보고 재구성할 수 있어야 한다."""
    d = json.loads(to_json(_block()))
    assert d["thresholds"]["min_effect_size"] == 0.05
    assert d["thresholds"]["min_corporate_resolution_rate"] == 0.8


def test_both_sweeps_are_reported():
    """AC-7(해상도) 과 AC-8(겹2 계수) 은 별개 축이라 따로 나와야 한다."""
    s = json.loads(to_json(_block()))["verification"]["stability"]
    assert set(s) == {"resolution", "coefficients"}
    assert s["coefficients"]["largest_ratio"] == 1.04


def test_verification_carries_null_model_not_just_modularity():
    """모듈러리티만 내면 절대 기준으로 오독된다."""
    d = json.loads(to_json(_block()))
    v = d["verification"]["structure"]
    assert v["null_mean"] == 0.7230 and v["runs"] == 20
    assert v["effect_size"] == round(0.8535 - 0.7230, 6)


def test_failed_shuffles_are_visible():
    """셔플이 실패하면 귀무모형이 실제값 쪽으로 끌려가 효과크기가 작게 나온다.

    보수적인 방향이라 거짓 채택은 안 생기지만, 그 사실이 숫자만 봐선 안 보인다.
    그래서 반복수와 함께 실패 횟수도 싣는다.
    """
    v = json.loads(to_json(_block()))["verification"]["structure"]
    assert v["swaps_failed"] == 0


def test_cpm_delta_is_exposed():
    d = json.loads(to_json(_block()))
    assert d["verification"]["structure"]["cpm_delta"] == 14


def test_verdict_serializes_as_string():
    d = json.loads(to_json(_block()))
    assert d["verdict"] == "accepted"


def test_json_roundtrips():
    assert json.loads(to_json(_block())) == json.loads(to_json(_block()))
