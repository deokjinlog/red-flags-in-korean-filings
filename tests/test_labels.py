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


def test_warning_tier_is_separate_from_distress():
    """관리종목 지정은 되돌릴 수 있다 — 부실과 한 덩어리로 섞으면 뜻이 바뀐다."""
    from dartweave.signal.labels import (
        DISTRESS_TYPES,
        is_adverse,
        is_distress,
        is_warning,
    )

    assert is_warning("관리종목(부실 사유)")
    assert not is_distress("관리종목(부실 사유)")
    assert "관리종목(부실 사유)" not in DISTRESS_TYPES
    # 기본값은 꺼져 있어야 한다. 켜는 쪽이 표본이 두 배라 늘 유리해 보인다.
    assert not is_adverse("관리종목(부실 사유)")
    assert is_adverse("관리종목(부실 사유)", include_warning=True)
    # 부실은 어느 쪽에서도 부실이다.
    assert is_adverse("회생") and is_adverse("회생", include_warning=True)


def test_admin_designation_classifier_splits_size_from_distress():
    """시총·주가 미달은 '작다' 는 뜻이다 — 부실로 세면 규모 통제와 충돌한다."""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    from collect_kind_admin_history import event_of, reason_of

    assert reason_of("관리종목지정(시가총액 미달)") == ("규모·유동성", False)
    assert reason_of("관리종목지정(자본잠식률 50% 이상 등)") == ("자본잠식", True)
    # 스팩이 폐지절차보다 먼저 걸려야 한다 — 껍데기의 예정된 청산이다.
    assert reason_of("관리종목지정(SPAC 상장예비심사청구서 미제출 등)") == ("스팩", False)
    # 중첩 괄호. 비탐욕으로 자르면 "반기검토(감사" 만 남아 '부적정' 을 못 본다.
    assert reason_of("관리종목지정(반기검토(감사)의견 부적정, 의견거절)")[0] == "감사"
    # 사유가 제목에 없으면 '없음' 이 아니라 '모름' 이다.
    assert reason_of("관리종목지정") == ("사유불명", None)

    # "지정" 이라는 글자만 보면 안 된다 — 같은 사건을 여러 번 세게 된다.
    assert event_of("내부결산시점 관리종목 지정ㆍ형식적 상장폐지ㆍ상장적격성 실질심사 "
                    "사유 발생") == "내부결산 사유발생"
    assert event_of("주권매매거래정지(관리종목지정사유발생)") == "거래정지"
    assert event_of("신주인수권증권 상장폐지(기초주권의 관리종목 지정)") == "파생상품"
    assert event_of("관리종목지정(상장폐지사유 발생)") == "지정"


def test_bad_disclosure_does_not_count_the_cleared():
    """'불성실공시법인미지정' 은 심의 끝에 지정 안 한 것이다 — 세면 무혐의를 유죄로 센다."""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    from collect_kind_bad_disclosure import reason_of, status_of

    assert status_of("불성실공시법인지정(공시번복)") == ("지정", True)
    # 아래 셋은 문자열에 '지정' 이 들어 있지만 신호가 아니다.
    assert status_of("불성실공시법인미지정(지정유예)") == ("미지정", False)
    assert status_of("불성실공시법인지정예고(공시불이행)") == ("지정예고", False)
    assert status_of("[채권]채권상장법인불성실공시") == ("채권", False)
    # 사유는 겹칠 수 있다. 하나로 접지 않는다.
    assert reason_of("불성실공시법인지정(공시번복,공시불이행)") == "공시번복+공시불이행"
    assert reason_of("불성실공시법인지정") == "사유불명"


def test_bad_disclosure_excludes_the_shadow_events():
    """지정되면 거래정지가 따라붙는다 — 같은 사건이라 따로 세면 한 회사를 두 번 센다."""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    from collect_kind_bad_disclosure import status_of, violations_of

    assert status_of("주권매매거래정지(불성실공시법인 지정)") == ("거래정지(그림자)", False)
    # 다른 제도인데 제목에 '불성실공시' 가 들어가 딸려온다.
    assert status_of("불성실공시(의결권공시)") == ("의결권공시", False)
    assert status_of("불성실공시법인지정(공시번복)") == ("지정", True)

    # 제목에 위반 건수가 붙는다. 벌점은 본문에 있어 여기서 못 뽑는다.
    assert violations_of("불성실공시법인지정(공시번복 3건)") == 3
    assert violations_of("불성실공시법인지정(공시번복)") == 1


def test_kind_collectors_stop_when_a_page_repeats():
    """끝을 넘기면 빈 응답이 아니라 마지막 장이 되풀이돼 온다 — 조용히 불어난다."""
    from pathlib import Path

    for name in ("collect_kind_admin_history", "collect_kind_bad_disclosure"):
        src = Path(f"scripts/{name}.py").read_text(encoding="utf-8")
        assert "page_rows == prev_page" in src, name
        assert "되풀이" in src, name
    # 상장폐지 수집기는 '새 행이 없으면 중단' 으로 같은 것을 막는다.
    assert "len(seen) == before" in Path("scripts/collect_delisting.py").read_text(
        encoding="utf-8")
