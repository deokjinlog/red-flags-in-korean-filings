from dartweave.parse.relation import EdgeType, Source
from dartweave.parse.structured_rel import parse_major_shareholder

PAYLOAD = {
    "status": "000",
    "list": [
        {
            "corp_code": "00126380",
            "nm": "삼성생명보험",
            "relate": "최대주주",
            "trmend_posesn_stock_qota_rt": "8.51",
            "rcept_no": "20260311000123",
            "stlm_dt": "2025-12-31",
        },
        {
            "corp_code": "00126380",
            "nm": "삼성물산",
            "relate": "특수관계인",
            "trmend_posesn_stock_qota_rt": "5.01",
            "rcept_no": "20260311000123",
            "stlm_dt": "2025-12-31",
        },
    ],
}


def test_builds_shareholder_edges():
    edges = parse_major_shareholder(PAYLOAD)
    assert len(edges) == 2
    e = edges[0]
    assert e.edge_type is EdgeType.MAJOR_SHAREHOLDER_OF
    assert e.source_name == "삼성생명보험"
    assert e.target_corp_code == "00126380"
    assert e.share_pct == 8.51


def test_carries_provenance_and_scope():
    e = parse_major_shareholder(PAYLOAD)[0]
    assert e.rcept_no == "20260311000123"
    assert e.fiscal_year == "2026"
    assert e.as_of == "20251231"
    assert e.source is Source.STRUCTURED
    assert e.confidence is None


def test_unparsable_ratio_becomes_none_not_zero():
    payload = {
        "status": "000",
        "list": [
            {
                "corp_code": "00126380",
                "nm": "미상",
                "trmend_posesn_stock_qota_rt": "-",
                "rcept_no": "20260311000123",
                "stlm_dt": "2025-12-31",
            }
        ],
    }
    assert parse_major_shareholder(payload)[0].share_pct is None


def test_comma_separated_ratio_is_parsed():
    payload = {
        "status": "000",
        "list": [
            {
                "corp_code": "00126380",
                "nm": "x",
                "trmend_posesn_stock_qota_rt": "1,234.5",
                "rcept_no": "20260311000123",
                "stlm_dt": "2025-12-31",
            }
        ],
    }
    assert parse_major_shareholder(payload)[0].share_pct == 1234.5
