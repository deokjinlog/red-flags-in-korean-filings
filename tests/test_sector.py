from dartweave.screen.sector import MIN_PEERS, is_shell, name_of, sector_of


def test_rolls_up_to_two_digits():
    """DART 업종코드는 3~5 자리로 뒤섞여 있다 — 세분류로는 업종당 2 사뿐이다."""
    assert sector_of("58222") == "58"
    assert sector_of("239") == "23"
    assert sector_of(2612) == "26"


def test_unknown_code_yields_no_sector():
    """이름을 모르는 코드로 '업종 대비' 를 말할 수는 없다."""
    assert sector_of("99") is None
    assert sector_of(None) is None


def test_names_are_readable():
    assert name_of("26") == "전자·반도체"
    assert name_of("41") == "종합 건설"


def test_peer_floor_matches_test_discipline():
    assert MIN_PEERS == 20


def test_shell_companies_are_excluded_from_comparison():
    """스팩은 영업손실이 구조적으로 확정이라 '동종' 이 아니다."""
    assert is_shell("유진스팩10호")
    assert is_shell("엔에이치기업인수목적29호")
    assert not is_shell("풍원정밀")
    assert not is_shell(None)
