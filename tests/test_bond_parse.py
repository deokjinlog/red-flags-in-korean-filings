"""전환사채 발행결정 파싱 — 조항까지."""
from dartweave.parse.bond import parse_bond

REAL = """
<TR><TE ACODE="DNM_SUM">20,000,000,000</TE><TE ACODE="ISSU_MTH">사모</TE></TR>
<TR><TE ACODE="EXE_PRC">1,295</TE><TE ACODE="STK_CNT">15,444,015</TE>
    <TE ACODE="STK_RT">26.42</TE></TR>
<TR><TE ACODE="MIN_PRC">907</TE><TE ACODE="EXP_DT">2027년 05월 30일</TE></TR>
<TR><TE ACODE="OPT_FCT">조기상환청구권 (Put Option)에 관한 사항 ...</TE></TR>
"""


def test_reads_overhang_the_filer_reported():
    """오버행은 우리가 계산할 필요가 없다 — 제출사가 신고한 값이 코드로 온다."""
    b = parse_bond(REAL)
    assert b.overhang_pct == 26.42 and b.exercise_price == 1295.0


def test_refix_depth_is_relative_to_exercise_price():
    """하한 907원 자체보다 '전환가의 70%' 라는 게 희석 폭을 말한다."""
    assert round(parse_bond(REAL).refix_depth, 1) == 70.0


def test_put_and_call_are_read_from_the_option_text():
    """풋/콜은 코드가 없고 한 칸에 서술로 온다 — 분류지 추출이 아니다."""
    b = parse_bond(REAL)
    assert b.has_put and not b.has_call
    call = REAL.replace("조기상환청구권 (Put Option)", "매도청구권(Call Option)")
    assert parse_bond(call).has_call


def test_missing_refix_floor_is_unknown_not_zero():
    """하한 '-' 를 0 으로 읽으면 '액면가까지 열림' 이라는 최악을 만들어낸다."""
    b = parse_bond(REAL.replace('<TE ACODE="MIN_PRC">907</TE>',
                                '<TE ACODE="MIN_PRC">-</TE>'))
    assert b.refix_floor is None and b.refix_depth is None


def test_public_offering_is_not_private():
    assert parse_bond(REAL.replace(">사모<", ">공모<")).private is False


def test_document_without_codes_returns_none():
    """코드가 없으면 조용히 0 으로 채우지 않는다."""
    assert parse_bond("<TR><TD>전환사채 발행결정</TD></TR>") is None
