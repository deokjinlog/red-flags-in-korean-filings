"""법인/자연인 분리 — 해소율 지표가 정상 상태를 불합격 처리하지 않게.

샘플은 전부 실 API 응답에서 가져왔다 (2026-08-13~14 실측).
"""
from dartweave.resolve.classify import EntityKind, classify_name
from dartweave.resolve.resolver import Resolver


def test_corporate_markers_are_detected():
    for nm in (
        "삼성생명보험㈜", "(주)케이티", "동진홀딩스주식회사",
        "재단법인 동진장학연구재단", "건설공제조합", "국민연금공단",
        "베어링자산운용",
    ):
        assert classify_name(nm) is EntityKind.CORPORATE, nm


def test_foreign_corporations_are_no_longer_lumped_into_corporate():
    """분류 체계가 3분류 → 4분류로 넓어지며 바뀐 지점.

    `TOKAI CARBON CO.,LTD.`·`PolarCapitalLLP` 는 Ltd/LLP 표지를 달았지만
    corpCode(국내 등록법인 명부)에 없다. 예전엔 CORPORATE 로 세서 '매핑 실패' 로
    잡혔는데, 실측상 미해소 표기의 56.7% 가 이 형태라 법인 해소율을 통째로 왜곡했다.
    """
    for nm in ("TOKAI CARBON CO.,LTD.", "PolarCapitalLLP"):
        assert classify_name(nm) is EntityKind.UNREGISTRABLE, nm


def test_natural_persons_are_detected():
    """실측: 홍라희·이재용 등은 corp_code 가 없어 미해소가 정상이다."""
    for nm in ("홍라희", "이재용", "이부진", "곽동신", "정지완", "나혁휘", "김정하"):
        assert classify_name(nm) is EntityKind.NATURAL, nm


def test_spaced_korean_names_are_natural():
    """실데이터에 '김 형 관' 처럼 공백이 낀 실명 표기가 있다."""
    for nm in ("김 형 관", "이 상 균", "정 기 선"):
        assert classify_name(nm) is EntityKind.NATURAL, nm


def test_latin_person_names_are_natural():
    assert classify_name("MIRA SUH-HEE CHOI") is EntityKind.NATURAL


def test_empty_is_unknown():
    assert classify_name("") is EntityKind.UNKNOWN
    assert classify_name("   ") is EntityKind.UNKNOWN


def test_suffixless_korean_company_names_are_unknown_not_natural():
    """접미사 없는 한글 법인명은 인명과 표기가 겹친다 — 삼성물산(4) vs 남궁민수(4).

    회사를 자연인으로 잘못 넣으면 **진짜 매핑 실패가 지표에서 사라진다.**
    그래서 모호한 건 NATURAL 이 아니라 UNKNOWN 으로 보낸다.
    (실제로 이 이름들은 corpCode 에 있어 해소 단계에서 법인으로 확정된다.)
    """
    for nm in ("삼성물산", "고려아연", "경방", "한화", "두산"):
        assert classify_name(nm) is EntityKind.UNKNOWN, nm


def test_resolution_wins_over_heuristic():
    """해소되면 표기 추정과 무관하게 법인이다 — corpCode 등재가 곧 증거."""
    r = Resolver({"삼성물산": "00149655"}, aliases={})
    assert classify_name("삼성물산") is EntityKind.UNKNOWN  # 표기만으로는 모호
    r.resolve("삼성물산", rcept_no="x")
    b = r.breakdown()
    assert b["corporate_resolved"] == 1 and b["unknown"] == 0


def test_resolution_rate_separates_natural_persons():
    """전체 해소율은 개인 때문에 낮아지지만, 법인 해소율은 그대로여야 한다.

    실측 배경: 삼성전자 최대주주 26건 중 법인은 4곳뿐이고 나머지는 개인이라
    전체 해소율이 29.7% 로 찍혔다. 이걸 품질 임계로 쓰면 정상이 불합격된다.
    """
    r = Resolver({"삼성생명보험㈜": "00139214", "삼성물산": "00149655"}, aliases={})
    for nm in ("삼성생명보험㈜", "삼성물산"):
        r.resolve(nm, rcept_no="x")
    for nm in ("홍라희", "이재용", "이부진", "홍석준", "이서현", "김재열"):
        r.resolve(nm, rcept_no="x")

    b = r.breakdown()
    assert b["corporate_attempts"] == 2
    assert b["corporate_resolved"] == 2
    assert b["natural_person"] == 6
    assert r.corporate_resolution_rate() == 1.0       # 법인은 전부 해소됨
    assert r.resolution_rate() == 0.25                 # 전체는 개인 때문에 낮음


def test_unresolved_corporate_is_a_real_problem():
    """법인인데 미해소면 그건 진짜 매핑 실패다 — 분모에 남아야 한다."""
    r = Resolver({"삼성물산": "00149655"}, aliases={})
    r.resolve("삼성물산", rcept_no="x")
    r.resolve("듣보잡홀딩스주식회사", rcept_no="x")
    r.resolve("홍길동", rcept_no="x")

    b = r.breakdown()
    assert b["corporate_attempts"] == 2
    assert b["corporate_unresolved"] == 1
    assert b["natural_person"] == 1
    assert r.corporate_resolution_rate() == 0.5


def test_breakdown_covers_every_attempt():
    """분해 합이 전체 시도와 맞아야 한다 — 어디로도 안 새야 한다."""
    r = Resolver({"삼성물산": "00149655"}, aliases={})
    for nm in ("삼성물산", "홍길동", "듣보잡홀딩스주식회사", "???"):
        r.resolve(nm, rcept_no="x")
    b = r.breakdown()
    assert b["corporate_attempts"] + b["natural_person"] + b["unknown"] == b["attempts"]


# --- D10 · D11: 정규화가 놓친 패턴 (실측) -----------------------------------


def test_corporate_mark_is_stripped_anywhere_not_just_edges():
    """D10 실측: '삼성생명보험㈜\\n(특별계정)' 은 ㈜ 가 중간이라 접두/접미 제거로는 안 지워졌다."""
    from dartweave.resolve.normalize import normalize_name

    assert normalize_name("삼성생명보험㈜\n(특별계정)") == "삼성생명보험(특별계정)"
    assert normalize_name("(주)케이티") == "케이티"
    assert normalize_name("삼성전자㈜") == "삼성전자"


def test_legal_form_prefixes_are_stripped():
    """D11 실측: corpCode 정식명칭은 '사회복지법인삼성생명공익재단' 인데 공시는 접두사를 뺀다."""
    from dartweave.resolve.normalize import normalize_name

    assert normalize_name("사회복지법인삼성생명공익재단") == "삼성생명공익재단"
    assert normalize_name("삼성생명공익재단") == "삼성생명공익재단"
    assert normalize_name("재단법인 동진장학연구재단") == "동진장학연구재단"


def test_parenthetical_account_suffix_is_preserved():
    """'(특별계정)' 은 계정 구분이지 표기 기호가 아니다.

    임의로 지워 본체와 합치면 별개 보유 주체가 하나로 뭉친다. 미해소로 남겨
    대기열 → 별칭 사전으로 사람이 판단하게 한다 (요구사항 결정 8-a).
    """
    from dartweave.resolve.normalize import normalize_name

    assert "(특별계정)" in normalize_name("삼성생명보험㈜(특별계정)")
