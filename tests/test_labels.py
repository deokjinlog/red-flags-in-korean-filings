"""무엇을 '부실' 로 셀 것인가."""
from dartweave.signal.labels import DISTRESS_TYPES, is_distress


def test_dart_distress_types_count():
    for t in ("부도", "회생", "관리절차", "파산"):
        assert is_distress(t)


def test_dissolution_is_not_distress():
    """실측 — 해산 52건을 뽑았더니 PFV·SPC 의 만기 해산이 대부분이었다."""
    assert not is_distress("해산(부실아님)")


def test_merger_and_spac_delistings_are_not_distress():
    """상장폐지 493건 중 과반이 부실이 아니다 — 세면 라벨이 통째로 오염된다."""
    for t in ("상장폐지(합병)", "상장폐지(스팩청산)", "상장폐지(이전상장)",
              "상장폐지(자진)", "상장폐지(지정자문인)", "상장폐지(해산)",
              "상장폐지(요건 미달)", "상장폐지(기타)"):
        assert not is_distress(t), t


def test_distress_delistings_are_counted():
    for t in ("상장폐지(감사의견)", "상장폐지(실질심사)", "상장폐지(파산)",
              "상장폐지(보고서 미제출)"):
        assert is_distress(t), t


def test_unknown_type_is_not_distress():
    """모르는 유형은 세지 않는다 — 없는 신호를 만드는 것보다 놓치는 쪽이 낫다."""
    assert not is_distress("새로 생긴 사유")
    assert not is_distress("")


def test_no_type_is_both_counted_and_excluded():
    assert "해산(부실아님)" not in DISTRESS_TYPES
    assert len(DISTRESS_TYPES) == 9


def test_business_suspension_is_excluded():
    """금융회사의 영업정지는 당국 제재지 부실이 아니다.

    답안지에 신한은행(557조)·하나은행(532조·21건)·우리은행이 들어가 있었다.
    빼니까 신호가 전부 강해졌다 — 오염이 신호를 깎고 있었다.
    """
    from dartweave.signal.labels import EXCLUDED_AMBIGUOUS, is_distress
    assert not is_distress("영업정지")
    assert "영업정지" in EXCLUDED_AMBIGUOUS
    # 진짜 부실은 그대로 센다
    for t in ("부도", "회생", "관리절차", "파산", "상장폐지(감사의견)"):
        assert is_distress(t), t


def test_final_default_delisting_counts_as_distress():
    """최종부도로 인한 폐지가 '기타' 로 떨어져 부실에서 빠져 있었다."""
    from dartweave.signal.labels import is_distress

    assert is_distress("상장폐지(부도)")
    # 예정된 종료는 여전히 부실이 아니다.
    assert not is_distress("상장폐지(존속기간 만료)")


def test_delisting_classifier_leaves_no_other_bucket():
    """'기타' 가 남아 있으면 그 안에 부실이 섞여 있는지 아무도 모른다."""
    import json
    from pathlib import Path
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    from collect_delisting import classify

    # 실제로 '기타' 로 떨어져 있던 두 종류
    assert classify("발행한 어음 또는 수표가 주거래은행에 의하여 최종부도로 결정되거나 "
                    "거래은행에 의한 거래정지") == "상장폐지(부도)"
    assert classify("존속기간 만료") == "상장폐지(존속기간 만료)"

    src = Path("data/delisting.json")
    if src.exists():
        rows = json.loads(src.read_text(encoding="utf-8"))
        assert not [r for r in rows if classify(r["reason"]) == "상장폐지(기타)"]
