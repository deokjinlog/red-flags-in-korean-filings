from dartweave.parse.relation import EdgeType
from dartweave.parse.structured_rel import parse_auditor, parse_executives

EXEC = {
    "status": "000",
    "list": [
        {
            "corp_code": "00126380",
            "nm": "홍길동",
            "ofcps": "대표이사",
            "rcept_no": "20260311000123",
            "stlm_dt": "2025-12-31",
        },
        {
            "corp_code": "00126380",
            "nm": "",
            "ofcps": "사외이사",
            "rcept_no": "20260311000123",
            "stlm_dt": "2025-12-31",
        },
    ],
}

AUDITOR = {
    "status": "000",
    "list": [
        {
            "corp_code": "00126380",
            "adtor": "삼일회계법인",
            "adt_opinion": "적정",
            "rcept_no": "20260311000123",
            "stlm_dt": "2025-12-31",
        }
    ],
}


def test_executive_edges_skip_blank_names():
    edges = parse_executives(EXEC)
    assert len(edges) == 1
    assert edges[0].edge_type is EdgeType.EXECUTIVE_OF
    assert edges[0].source_name == "홍길동"


def test_auditor_edge_direction_is_company_to_auditor():
    e = parse_auditor(AUDITOR)[0]
    assert e.edge_type is EdgeType.AUDITED_BY
    assert e.source_corp_code == "00126380"
    assert e.target_name == "삼일회계법인"


def test_people_and_auditor_edges_have_no_share_pct():
    assert parse_executives(EXEC)[0].share_pct is None
    assert parse_auditor(AUDITOR)[0].share_pct is None
