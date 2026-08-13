"""합산 지분 대조 축 테스트.

payload 는 실 API 응답의 필드 구성을 그대로 따른다 (2026-08-13 실측).
계약 fixture 를 계획서의 가정대로 만들었다가 결함 7건을 놓친 전례가 있어서,
이 파일의 샘플은 전부 실제 응답에서 가져왔다.
"""
from dartweave.parse.structured_rel import parse_major_shareholder
from dartweave.trust.aggregate import (
    AggResult,
    cross_check_aggregate,
    group_members,
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
            "relate": "최대주주 본인",
            "trmend_posesn_stock_co": "508,157,148",
            "trmend_posesn_stock_qota_rt": "8.51",
            "stlm_dt": "2024-12-31",
        },
        {
            "rcept_no": "20250311001085",
            "corp_code": "00126380",
            "stock_knd": "보통주",
            "nm": "삼성물산",
            "relate": "계열회사",
            "trmend_posesn_stock_co": "298,818,100",
            "trmend_posesn_stock_qota_rt": "5.01",
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
    assert [e.source_name for e in edges] == ["삼성생명보험㈜", "삼성물산"]
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


def test_large_divergence_needs_review():
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
    assert checks[0].status is AggResult.NEEDS_REVIEW
    assert checks[0].detail["pct_by_company"] == 20.07
    assert checks[0].detail["pct_by_holder"] == 8.40


def test_reporter_must_belong_to_the_group():
    """대표보고자는 최대 지분권자가 아닐 수 있다.

    실측: 삼성전자의 최대주주 본인은 삼성생명(8.51%)인데 대량보유 보고자는
    삼성물산(5.01%)이다. 본인 이름으로만 짝지으면 이 정상 사례를 놓친다.
    반대로 국민연금처럼 특별관계자가 아닌 보고자는 배제되어야 한다.
    """
    members = group_members(HYSLR)
    assert "삼성물산" in {m for m in members}
    outsider = {
        "status": "000",
        "list": [
            {
                "rcept_no": "20241007000111",
                "rcept_dt": "2024-10-07",
                "corp_code": "00126380",
                "repror": "국민연금공단",
                "stkqy": "400,000,000",
                "stkrt": "6.70",
            }
        ],
    }
    checks = cross_check_aggregate(
        parse_holding_aggregates(HYSLR), parse_major_reports(outsider)
    )
    assert checks[0].status is AggResult.NO_REPORT


def test_preferred_stock_aggregate_is_not_compared():
    """「대량보유 상황보고」의 '주식등' 은 종류 통합이라 우선주 계행과 맞대면 안 된다."""
    payload = {
        "status": "000",
        "list": [
            {
                "rcept_no": "r",
                "corp_code": "00126380",
                "stock_knd": "우선주",
                "nm": "계",
                "trmend_posesn_stock_co": "993,638",
                "trmend_posesn_stock_qota_rt": "0.12",
                "stlm_dt": "2024-12-31",
            }
        ],
    }
    assert parse_holding_aggregates(payload) == []


def test_gap_is_explained_by_the_missing_shareholder():
    """실측(동진쎄미켐): 차액 1,880,000주 = 재단법인 동진장학연구재단 보유분.

    「대량보유 상황보고」는 합계만 주고 구성원 명단을 안 준다. 따라서 "누가 한쪽에만
    있는가" 는 차액 역산으로만 알 수 있고, 이 분해가 없으면 판정에 원문 추적이 필요하다.
    """
    hyslr = {
        "status": "000",
        "list": [
            {
                "rcept_no": "r", "corp_code": "00118804", "stock_knd": "보통주",
                "nm": "동진홀딩스주식회사", "relate": "최대주주",
                "trmend_posesn_stock_co": "16,706,986",
                "trmend_posesn_stock_qota_rt": "32.49", "stlm_dt": "2024-12-31",
            },
            {
                "rcept_no": "r", "corp_code": "00118804", "stock_knd": "보통주",
                "nm": "재단법인 동진장학연구재단", "relate": "기타",
                "trmend_posesn_stock_co": "1,880,000",
                "trmend_posesn_stock_qota_rt": "3.66", "stlm_dt": "2024-12-31",
            },
            {
                "rcept_no": "r", "corp_code": "00118804", "stock_knd": "보통주",
                "nm": "명부산업(주)", "relate": "기타",
                "trmend_posesn_stock_co": "633,678",
                "trmend_posesn_stock_qota_rt": "1.23", "stlm_dt": "2024-12-31",
            },
            {
                "rcept_no": "r", "corp_code": "00118804", "stock_knd": "보통주",
                "nm": "계", "trmend_posesn_stock_co": "19,220,664",
                "trmend_posesn_stock_qota_rt": "37.38", "stlm_dt": "2024-12-31",
            },
        ],
    }
    report = {
        "status": "000",
        "list": [{
            "rcept_no": "m", "rcept_dt": "2024-12-06", "corp_code": "00118804",
            "repror": "동진홀딩스주식회사",
            "stkqy": "17,340,664", "stkrt": "33.72",
        }],
    }
    checks = cross_check_aggregate(
        parse_holding_aggregates(hyslr), parse_major_reports(report)
    )
    assert checks[0].status is AggResult.NEEDS_REVIEW
    d = checks[0].detail
    assert d["gap_qty"] == 1_880_000
    assert ("재단법인 동진장학연구재단",) in d["gap_explained_by"]


def test_unexplained_gap_returns_empty_and_that_is_the_signal():
    """설명이 안 되면 빈 목록. 억지로 조합을 만들어 설명한 척하면 안 된다."""
    from dartweave.trust.aggregate import explain_gap
    assert explain_gap((("A", 100), ("B", 200)), 7777) == []
