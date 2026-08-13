from dartweave.dart.company import parse_company

PAYLOAD = {
    "status": "000",
    "corp_name": "삼성전자(주)",
    "corp_name_eng": "SAMSUNG ELECTRONICS CO,.LTD",
    "stock_name": "삼성전자",
    "stock_code": "005930",
    "corp_cls": "Y",
    "induty_code": "26410",
    "est_dt": "19690113",
    "acc_mt": "12",
}


def test_extracts_industry_and_class():
    c = parse_company("00126380", PAYLOAD)
    assert c.corp_code == "00126380"
    assert c.induty_code == "26410"
    assert c.corp_cls == "Y"


def test_missing_optional_fields_become_none():
    c = parse_company("00999999", {"status": "000", "corp_name": "무명"})
    assert c.induty_code is None
    assert c.stock_code is None
    assert c.corp_name == "무명"


def test_blank_string_is_none_not_empty():
    c = parse_company("00999999", {"status": "000", "corp_name": "x", "induty_code": " "})
    assert c.induty_code is None
