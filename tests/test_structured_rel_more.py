from dartweave.parse.relation import EdgeType
from dartweave.parse.structured_rel import parse_investment, parse_major_holding

INVEST = {
    "status": "000",
    "list": [
        {
            "corp_code": "00126380",
            "inv_prm": "삼성디스플레이",
            # 실 API 응답 필드명 (2026-08-13 실측). 계획서 초안의 trmend_qota_rt 는
            # 존재하지 않는 키였고, fixture 가 같은 오타를 공유해 통과하고 있었다.
            "trmend_blce_qota_rt": "84.8",
            "rcept_no": "20260311000123",
            "stlm_dt": "2025-12-31",
        }
    ],
}

HOLDING = {
    "status": "000",
    "list": [
        {
            "corp_code": "00164779",
            "repror": "국민연금공단",
            # 실 API 응답 필드 (2026-08-13 실측). 초안의 stkqy_irds_rt 는 없는 키였고
            # fixture 가 같은 오타를 공유해 통과하고 있었다.
            "stkrt": "7.12",
            "stkqy": "51,830,000",
            "rcept_no": "20260201000777",
            "stlm_dt": "2026-01-31",
        }
    ],
}


def test_investment_edge_direction_is_holder_to_investee():
    e = parse_investment(INVEST)[0]
    assert e.edge_type is EdgeType.INVESTS_IN
    assert e.source_corp_code == "00126380"
    assert e.target_name == "삼성디스플레이"
    assert e.share_pct == 84.8


def test_major_holding_edge():
    e = parse_major_holding(HOLDING)[0]
    assert e.edge_type is EdgeType.HOLDS_5PCT
    assert e.source_name == "국민연금공단"
    assert e.target_corp_code == "00164779"
    assert e.share_pct == 7.12


def test_reporter_is_recorded_for_cross_check():
    """교차확인은 '누가 신고했나'를 알아야 성립한다."""
    assert parse_investment(INVEST)[0].reporter_corp_code == "00126380"
    assert parse_major_holding(HOLDING)[0].reporter_corp_code == "00164779"
