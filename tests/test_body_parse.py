"""공시 원문 파싱 — DART 가 셀에 붙여둔 코드를 읽는다."""
from dartweave.parse.body import coded_rows, extract_investments

REAL = """
<TABLE><TR>
  <TE ACODE="INV_PRM">㈜금강레저</TE><TU AUNIT="INV_YN">비상장</TU>
  <TE ACODE="INV_BPR">18.00</TE><TE ACODE="INV_LPR">20.50</TE>
</TR><TR>
  <TE ACODE="INV_PRM">SIC Investment Ltd</TE><TE ACODE="INV_LPR">-</TE>
</TR><TR>
  <TD>본문 문단이라 코드가 없다</TD>
</TR></TABLE>
"""


def test_reads_dart_semantic_codes_not_column_positions():
    """열 위치나 헤더 문구를 추측하지 않는다 — 제출사마다 표가 달라도 코드는 같다."""
    rows = coded_rows(REAL)
    assert len(rows) == 2                     # 코드 없는 행은 버린다
    assert rows[0]["INV_PRM"] == "㈜금강레저"


def test_uses_closing_share_not_opening():
    """정형 API 는 보고서 기준일 보유를 준다 — 기초를 쓰면 한 해 어긋난 값과 대조하게 된다."""
    got = {x.name: x.share_pct for x in extract_investments(REAL)}
    assert got["㈜금강레저"] == 20.50         # INV_LPR, INV_BPR(18.00) 아님


def test_dash_becomes_unknown_not_zero():
    """'-' 를 0 으로 읽으면 지분 없는 회사를 만들어낸다."""
    got = {x.name: x.share_pct for x in extract_investments(REAL)}
    assert got["SIC Investment Ltd"] is None


def test_out_of_range_percent_is_rejected():
    """수량·금액 칸이 지분율로 새어 들어오면 100 을 넘는다."""
    xml = '<TR><TE ACODE="INV_PRM">A</TE><TE ACODE="INV_LPR">355,898,377</TE></TR>'
    assert extract_investments(xml)[0].share_pct is None


def test_same_company_twice_keeps_the_one_with_a_number():
    xml = ('<TR><TE ACODE="INV_PRM">A</TE><TE ACODE="INV_LPR">-</TE></TR>'
           '<TR><TE ACODE="INV_PRM">A</TE><TE ACODE="INV_LPR">12.34</TE></TR>')
    got = extract_investments(xml)
    assert len(got) == 1 and got[0].share_pct == 12.34


def test_empty_document_is_not_an_error():
    assert extract_investments("") == []
    assert coded_rows("<TABLE></TABLE>") == []
