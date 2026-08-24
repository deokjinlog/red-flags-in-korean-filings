from datetime import date

from dartweave.screen.calendar import Due, due_within, parse_maturity


def test_parses_both_maturity_formats():
    """실측 8,878건 중 한글 형식은 3,634건뿐 — 한쪽만 받으면 절반을 버린다."""
    assert parse_maturity("2027년 07월 30일") == date(2027, 7, 30)
    assert parse_maturity("2029.04.12") == date(2029, 4, 12)
    assert parse_maturity("2027-10-12") == date(2027, 10, 12)


def test_rejects_unparseable_rather_than_guessing():
    assert parse_maturity(None) is None
    assert parse_maturity("만기일 미정") is None
    assert parse_maturity("2027년 13월 01일") is None      # 없는 달


def test_counts_only_bonds_issued_before_the_base_date():
    """기준일 뒤에 발행된 사채를 세면 미래를 훔쳐본다."""
    rows = [
        {"amount": 100.0, "maturity": "2026.01.01", "has_put": True},   # 창 안
        {"amount": 200.0, "maturity": "2030.01.01", "has_put": False},  # 창 밖
        {"amount": 400.0, "maturity": "2024.01.01", "has_put": False},  # 이미 지남
    ]
    d = due_within(rows, date(2025, 6, 30), years=2)
    assert d == Due(amount=100.0, count=1, with_put=1)
    assert d.has_put


def test_empty_is_zero_not_unknown():
    """사채가 없는 회사는 '모른다' 가 아니라 갚을 게 0 이다."""
    assert due_within([], date(2025, 6, 30)) == Due(0.0, 0, 0)
