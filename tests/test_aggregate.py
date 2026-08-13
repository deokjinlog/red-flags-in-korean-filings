"""합산 지분 대조 축 테스트.

payload 는 실 API 응답의 필드 구성을 그대로 따른다 (2026-08-13 실측).
계약 fixture 를 계획서의 가정대로 만들었다가 결함 7건을 놓친 전례가 있어서,
이 파일의 샘플은 전부 실제 응답에서 가져왔다.
"""
from dartweave.parse.structured_rel import parse_major_shareholder
from dartweave.trust.aggregate import (
    AggResult,
    cross_check_aggregate,
    latest_report_before,
    parse_holding_aggregates,
    parse_major_reports,
)

# 삼성전자 「최대주주 현황」 (2024 사업보고서) — 개별 행 + 계 행
HYSLR = {
    "status": "000",
    "list": [
        {
            "rcept_no": "20250311001085",
            "corp_code": "00126380",
            "stock_knd": "보통주",
            "nm": "삼성생명보험㈜",
            "trmend_posesn_stock_co": "508,157,148",
            "trmend_posesn_stock_qota_rt": "8.51",
            "stlm_dt": "2024-12-31",
        },
        {
            "rcept_no": "20250311001085",
            "corp_code": "00126380",
            "stock_knd": "보통주",
            "nm": "계",
            "trmend_posesn_stock_co": "1,198,033,154",
            "trmend_posesn_stock_qota_rt": "20.07",
            "stlm_dt": "2024-12-31",
        },
        {
            "rcept_no": "20250311001085",
            "corp_code": "00126380",
            "stock_knd": "기타",
            "nm": "계",
            "trmend_posesn_stock_co": "-",
            "trmend_posesn_stock_qota_rt": "-",
            "stlm_dt": "2024-12-31",
        },
    ],
}

# 삼성전자 「대량보유 상황보고」 — 보고자 기준 합산, 접수일 기반
MAJORSTOCK = {
    "status": "000",
    "list": [
        {
            "rcept_no": "20241025000530",
            "rcept_dt": "2024-10-25",
            "corp_code": "00126380",
            "repror": "삼성물산",
            "stkqy": "1,198,889,258",
            "stkrt": "20.08",
        },
        {
            "rcept_no": "20230510000111",
            "rcept_dt": "2023-05-10",
            "corp_code": "00126380",
            "repror": "삼성물산",
            "stkqy": "1,000,000,000",
            "stkrt": "16.75",
        },
    ],
}


def test_aggregate_rows_are_captured_separately_from_edges():
    """`계` 행은 주주 엣지가 되면 안 되지만, 합산 사실로는 살아 있어야 한다."""
    edges = parse_major_shareholder(HYSLR)
    aggs = parse_holding_aggregates(HYSLR)
    assert [e.source_name for e in edges] == ["삼성생명보험㈜"]
    assert len(aggs) == 1  # 값이 '-' 인 기타 계 행은 제외
    assert aggs[0].stock_knd == "보통주"
    assert aggs[0].share_qty == 1_198_033_154
    assert aggs[0].as_of == "20241231"


def test_major_report_uses_real_response_fields():
    """초안이 가정한 stkqy_irds_rt 는 실제 응답에 없다. stkrt / stkqy 가 맞다."""
    reports = parse_major_reports(MAJORSTOCK)
    assert reports[0].reporter == "삼성물산"
    assert reports[0].share_qty == 1_198_889_258
    assert reports[0].share_pct == 20.08
    assert reports[0].rcept_dt == "20241025"


def test_latest_report_before_picks_the_effective_one():
    """대량보유보고는 이벤트 기반이라 기준일과 날짜가 일치할 수 없다."""
    reports = parse_major_reports(MAJORSTOCK)
    picked = latest_report_before(reports, "20241231")
    assert picked is not None and picked.rcept_dt == "20241025"


def test_no_report_before_as_of_is_not_a_conflict():
    reports = parse_major_reports(MAJORSTOCK)
    assert latest_report_before(reports, "20220101") is None
    checks = cross_check_aggregate(parse_holding_aggregates(HYSLR), [])
    assert checks[0].status is AggResult.NO_REPORT


def test_real_pair_agrees_within_reporting_lag():
    """실측 짝: 계행 1,198,033,154주(12/31) vs 보고 1,198,889,258주(10/25).

    두 달 시차로 856,104주(0.07%p) 차이가 나지만 정상이다.
    """
    checks = cross_check_aggregate(
        parse_holding_aggregates(HYSLR), parse_major_reports(MAJORSTOCK)
    )
    assert len(checks) == 1
    assert checks[0].status is AggResult.CONFIRMED
    assert checks[0].counterpart is not None
    assert checks[0].counterpart.reporter == "삼성물산"


def test_large_divergence_is_a_conflict():
    """시차 허용치를 넘는 어긋남은 잡아야 한다 — 안 그러면 검출기가 무의미하다."""
    bogus = {
        "status": "000",
        "list": [
            {
                "rcept_no": "20241025000530",
                "rcept_dt": "2024-10-25",
                "corp_code": "00126380",
                "repror": "삼성물산",
                "stkqy": "500,000,000",
                "stkrt": "8.40",
            }
        ],
    }
    checks = cross_check_aggregate(
        parse_holding_aggregates(HYSLR), parse_major_reports(bogus)
    )
    assert checks[0].status is AggResult.CONFLICT
    assert checks[0].detail["pct_by_company"] == 20.07
    assert checks[0].detail["pct_by_holder"] == 8.40
