import io
import zipfile

from dartweave.dart.corpcode import parse_corpcode_zip

XML = """<?xml version="1.0" encoding="UTF-8"?>
<result>
  <list><corp_code>00126380</corp_code><corp_name>삼성전자</corp_name>
    <stock_code>005930</stock_code><modify_date>20260101</modify_date></list>
  <list><corp_code>00164779</corp_code><corp_name>SK하이닉스</corp_name>
    <stock_code>000660</stock_code><modify_date>20260102</modify_date></list>
  <list><corp_code>00999999</corp_code><corp_name>비상장회사</corp_name>
    <stock_code> </stock_code><modify_date>20260103</modify_date></list>
</result>
"""


def _zip_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("CORPCODE.xml", XML.encode("utf-8"))
    return buf.getvalue()


def test_parses_all_entries():
    rows = parse_corpcode_zip(_zip_bytes())
    assert len(rows) == 3
    assert rows[0].corp_code == "00126380"
    assert rows[0].corp_name == "삼성전자"


def test_blank_stock_code_becomes_none():
    rows = parse_corpcode_zip(_zip_bytes())
    assert rows[2].stock_code is None


def test_listed_only_filter():
    rows = parse_corpcode_zip(_zip_bytes(), listed_only=True)
    assert {r.corp_code for r in rows} == {"00126380", "00164779"}
