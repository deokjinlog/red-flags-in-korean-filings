"""무엇을 '부실' 로 셀 것인가."""
from dartweave.signal.labels import DISTRESS_TYPES, is_distress


def test_dart_distress_types_count():
    for t in ("부도", "회생", "관리절차", "파산", "영업정지"):
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
