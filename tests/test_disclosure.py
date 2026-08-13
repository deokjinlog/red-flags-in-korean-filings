from dartweave.dart.disclosure import fiscal_year_of, parse_disclosure_list

PAYLOAD = {
    "status": "000",
    "list": [
        {
            "corp_code": "00126380",
            "report_nm": "사업보고서 (2025.12)",
            "rcept_no": "20260311000123",
            "rcept_dt": "20260311",
        },
        {
            "corp_code": "00126380",
            "report_nm": "분기보고서 (2025.09)",
            "rcept_no": "20251114000456",
            "rcept_dt": "20251114",
        },
    ],
}


def test_fiscal_year_comes_from_rcept_no_prefix():
    assert fiscal_year_of("20260311000123") == "2026"


def test_parses_rows():
    rows = parse_disclosure_list(PAYLOAD)
    assert len(rows) == 2
    assert rows[0].rcept_no == "20260311000123"
    assert rows[0].fiscal_year == "2026"


def test_empty_status_yields_no_rows_and_no_error():
    assert parse_disclosure_list({"status": "013", "list": []}) == []


def test_report_name_filter():
    rows = parse_disclosure_list(PAYLOAD, name_contains="사업보고서")
    assert [r.rcept_no for r in rows] == ["20260311000123"]
