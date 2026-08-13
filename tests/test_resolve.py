from dartweave.resolve.normalize import normalize_name
from dartweave.resolve.resolver import Resolution, Resolver


def test_normalize_strips_corporate_suffix():
    assert normalize_name("삼성전자(주)") == "삼성전자"
    assert normalize_name("(주)삼성전자") == "삼성전자"
    assert normalize_name("삼성전자주식회사") == "삼성전자"


def test_normalize_collapses_whitespace_and_case():
    assert normalize_name("  SK   하이닉스 ") == "sk하이닉스"
    assert normalize_name("Samsung Electronics") == "samsungelectronics"


def test_resolves_via_official_name():
    r = Resolver({"삼성전자": "00126380"}, aliases={})
    res = r.resolve("삼성전자(주)", rcept_no="20250311000001")
    assert res.corp_code == "00126380"
    assert res.status is Resolution.RESOLVED


def test_resolves_via_alias_dictionary():
    r = Resolver({"삼성전자": "00126380"}, aliases={"samsungelectronics": "00126380"})
    assert r.resolve("Samsung Electronics", rcept_no="x").corp_code == "00126380"


def test_unresolved_returns_none_and_is_queued():
    r = Resolver({"삼성전자": "00126380"}, aliases={})
    res = r.resolve("듣보잡회사", rcept_no="20250311000001")
    assert res.corp_code is None
    assert res.status is Resolution.UNRESOLVED
    assert r.unresolved[0].surface_form == "듣보잡회사"


def test_resolution_rate_is_reported():
    r = Resolver({"삼성전자": "00126380"}, aliases={})
    r.resolve("삼성전자", rcept_no="x")
    r.resolve("삼성전자", rcept_no="x")
    r.resolve("모르는회사", rcept_no="x")
    assert r.resolution_rate() == 2 / 3


def test_never_invents_a_corp_code():
    """AC-10 — 미해소를 신규 코드로 조용히 만드는 경로가 없어야 한다."""
    r = Resolver({}, aliases={})
    assert r.resolve("무엇이든", rcept_no="x").corp_code is None
