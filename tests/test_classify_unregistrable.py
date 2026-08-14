"""corp_code 가 애초에 없는 대상 분리 — 자연인과 같은 이유, 같은 처방.

실측 배경 (2026-08-14, 표본 15사 · 표기 545건):
  미해소 법인 201건을 분류했더니 해외법인(영문) 56.7% · 펀드/조합/특별계정 34.3% 로
  **91%가 corpCode 에 존재할 수 없는 대상**이었다. corpCode 는 국내 등록법인 명부라
  해외 자회사도, 투자조합도, 보험 특별계정도 담지 않는다.

  이걸 '매핑 실패' 로 세면 개인 주주를 실패로 세던 것과 정확히 같은 범주 오류다.
  분모에서 빼면 법인 해소율이 44.5% → 89.9% 로, G1 임계 0.8 을 넘는다.
"""
from dartweave.resolve.classify import EntityKind, classify_name


def test_foreign_subsidiaries_are_not_registrable():
    """corpCode 는 국내 등록법인 명부다 — 해외 자회사는 원리적으로 못 찾는다.

    전부 실 API 응답에서 가져온 표기다.
    """
    for nm in (
        "Samsung SDI (Hong Kong) Ltd.",
        "SAMSUNG C&T CORPORATION VIETNAM CO., LTD",
        "POSCO INDIA CHENNAI STEEL PROCESSING CENTRE PVT LTD",
        "Trendy International (Shanghai Corso Como) Limited",
    ):
        assert classify_name(nm) is EntityKind.UNREGISTRABLE, nm


def test_funds_and_partnerships_are_not_registrable():
    """투자조합·사모펀드·특별계정은 법인 등록 대상이 아니다."""
    for nm in (
        "SVIC 70호 신기술사업투자조합",
        "우리일반사모부동산제1호투자유한회사",
        "삼성생명보험(특별계정)",
        "국민연금기금",
    ):
        assert classify_name(nm) is EntityKind.UNREGISTRABLE, nm


def test_domestic_corporations_stay_corporate():
    """국내 법인은 그대로 CORPORATE — 미해소면 그건 진짜 문제다."""
    for nm in ("삼성생명보험㈜", "(주)케이티", "동진홀딩스주식회사", "건설공제조합"):
        assert classify_name(nm) is EntityKind.CORPORATE, nm


def test_natural_persons_are_unchanged():
    for nm in ("홍라희", "이재용", "김 형 관"):
        assert classify_name(nm) is EntityKind.NATURAL, nm


def test_korean_name_with_latin_suffix_is_not_treated_as_foreign():
    """영문이 섞였다고 해외가 아니다 — 한글이 한 글자라도 있으면 국내 맥락이다.

    CORPORATE 를 단언하지 않는 이유: 접미사 없는 이름은 설계상 UNKNOWN 이다
    (`삼성물산` 과 같은 처지 — 모호하면 자연인으로도 법인으로도 확정하지 않는다).
    여기서 막으려는 건 **해외로 잘못 빼는 것**이다.
    """
    for nm in ("삼성SDI", "SK텔레콤"):
        assert classify_name(nm) is not EntityKind.UNREGISTRABLE, nm


def test_unregistrable_is_excluded_from_the_corporate_denominator():
    """핵심 — 자연인과 똑같이 분모에서 빠져야 한다.

    빼지 않으면 원리적으로 못 푸는 대상 때문에 G1 이 정상 상태를 불합격 처리한다.
    """
    from dartweave.resolve.resolver import Resolver

    r = Resolver({"삼성물산": "00149655"}, aliases={})
    r.resolve("삼성물산", rcept_no="x")                       # 법인 · 해소
    r.resolve("듣보잡홀딩스주식회사", rcept_no="x")              # 법인 · 미해소 = 진짜 문제
    r.resolve("Samsung SDI (Hong Kong) Ltd.", rcept_no="x")  # 등록 불가
    r.resolve("SVIC 70호 신기술사업투자조합", rcept_no="x")      # 등록 불가
    r.resolve("홍길동", rcept_no="x")                          # 자연인

    b = r.breakdown()
    assert b["corporate_attempts"] == 2
    assert b["corporate_unresolved"] == 1
    assert b["unregistrable"] == 2
    assert b["natural_person"] == 1
    assert r.corporate_resolution_rate() == 0.5


def test_breakdown_still_covers_every_attempt():
    """분해 합이 전체 시도와 맞아야 한다 — 새 구간이 생겨도 새면 안 된다."""
    from dartweave.resolve.resolver import Resolver

    r = Resolver({"삼성물산": "00149655"}, aliases={})
    for nm in ("삼성물산", "홍길동", "듣보잡홀딩스주식회사", "???",
               "Samsung SDI (Hong Kong) Ltd."):
        r.resolve(nm, rcept_no="x")
    b = r.breakdown()
    assert (
        b["corporate_attempts"] + b["natural_person"] + b["unregistrable"] + b["unknown"]
        == b["attempts"]
    )
