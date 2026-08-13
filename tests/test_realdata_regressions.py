"""실데이터가 드러낸 결함의 회귀 테스트.

2026-08-13 실 API 1회전에서 발견. 계약 fixture 만으로는 안 잡혔던 것들 —
fixture 를 계획서의 가정대로 만들었기 때문에 가정이 틀린 걸 알 수 없었다.
아래 payload 는 실제 응답에서 가져온 필드 구성이다.
"""
from dartweave.parse.relation import EdgeType, RelationEdge, Source
from dartweave.parse.structured_rel import parse_investment, parse_major_shareholder
from dartweave.trust.contradiction import detect_grade_a
from dartweave.trust.scope import Verdict, compare_scope, scope_key

# --- D1: 타법인 출자현황 지분율 필드 ---------------------------------------

REAL_INVESTMENT = {
    "status": "000",
    "list": [
        {
            "rcept_no": "20250311001085",
            "corp_code": "00126380",
            "inv_prm": "삼성전기㈜",
            "bsis_blce_qota_rt": "23.7",
            "trmend_blce_qy": "17,693,000",
            "trmend_blce_qota_rt": "23.7",
            "stlm_dt": "2024-12-31",
        }
    ],
}


def test_investment_share_pct_uses_real_response_field():
    """계획서는 trmend_qota_rt 를 가정했으나 실제 응답에 그 키는 없다.

    잘못된 필드를 읽으면 전건 None 이 되어 교차확인·모순검출이 통째로 무력화된다
    (실측: 삼성전자 138건 중 0건, SK하이닉스 49건 중 0건 파싱).
    """
    edge = parse_investment(REAL_INVESTMENT)[0]
    assert edge.share_pct == 23.7
    assert "trmend_qota_rt" not in REAL_INVESTMENT["list"][0]


# --- D2: 주식 종류 혼합 -----------------------------------------------------

REAL_SHAREHOLDER = {
    "status": "000",
    "list": [
        {
            "rcept_no": "20250311001085",
            "corp_code": "00164779",
            "stock_knd": "보통주",
            "nm": "SK㈜",
            "trmend_posesn_stock_qota_rt": "60.0",
            "stlm_dt": "2024-12-31",
        },
        {
            "rcept_no": "20250311001085",
            "corp_code": "00164779",
            "stock_knd": "의결권 있는 주식",
            "nm": "SK㈜",
            "trmend_posesn_stock_qota_rt": "60.0",
            "stlm_dt": "2024-12-31",
        },
    ],
}


def test_stock_knd_is_captured():
    edges = parse_major_shareholder(REAL_SHAREHOLDER)
    assert [e.stock_knd for e in edges] == ["보통주", "의결권 있는 주식"]


def test_duplicate_share_class_labels_do_not_fabricate_a_violation():
    """실측: SK하이닉스는 같은 지분을 '보통주'/'의결권 있는 주식' 으로 중복 게시한다.

    종류를 섞어 합산하면 60%+60%=120% 로 가짜 1급 모순이 만들어진다.
    종류별로 나눠 세면 각각 60% 라 위반이 아니다.
    """
    edges = parse_major_shareholder(REAL_SHAREHOLDER)
    assert detect_grade_a(edges) == []


def test_real_violation_within_one_share_class_is_still_caught():
    """종류별 분리가 진짜 위반까지 놓치면 안 된다."""
    payload = {
        "status": "000",
        "list": [
            {
                "rcept_no": "20250311001085",
                "corp_code": "00999999",
                "stock_knd": "보통주",
                "nm": f"주주{i}",
                "trmend_posesn_stock_qota_rt": "40.0",
                "stlm_dt": "2024-12-31",
            }
            for i in range(3)
        ],
    }
    findings = detect_grade_a(parse_major_shareholder(payload))
    assert len(findings) == 1
    assert findings[0].detail["total"] == 120.0
    assert findings[0].detail["stock_knd"] == "보통주"


# --- D3: fiscal_year 는 사업연도가 아니라 접수연도 ---------------------------


def _edge(rcept_no: str, as_of: str | None, pct: float) -> RelationEdge:
    return RelationEdge(
        edge_type=EdgeType.MAJOR_SHAREHOLDER_OF,
        source_name="A",
        source_corp_code=None,
        target_name=None,
        target_corp_code="B",
        rcept_no=rcept_no,
        fiscal_year=rcept_no[:4],
        as_of=as_of,
        source=Source.STRUCTURED,
        share_pct=pct,
    )


def test_scope_key_ignores_receipt_year_when_as_of_present():
    """실측: FY2024 사업보고서의 rcept_no 는 2025 로 시작한다 (접수연도).

    같은 기준일의 정정공시가 이듬해 접수되면, 접수연도를 스코프 키에 섞을 경우
    다른 버킷으로 갈라져 진짜 불일치가 CHANGE 로 오분류된다.
    """
    original = _edge("20250311001085", "20241231", 30.0)
    amended = _edge("20260105000001", "20241231", 25.0)
    assert scope_key(original) == scope_key(amended)
    assert compare_scope(original, amended) is Verdict.MISMATCH


def test_genuine_period_difference_is_still_change():
    a = _edge("20250311001085", "20241231", 30.0)
    b = _edge("20240311001085", "20231231", 25.0)
    assert compare_scope(a, b) is Verdict.CHANGE


def test_missing_as_of_still_falls_back_to_receipt_year():
    a = _edge("20250311001085", None, 30.0)
    b = _edge("20250315000009", None, 25.0)
    assert compare_scope(a, b) is Verdict.MISMATCH


# --- D5: 지분율 분모 불일치 (가장 위험했던 오탐) -----------------------------


def _qty_edge(pct: float, qty: int | None) -> RelationEdge:
    return RelationEdge(
        edge_type=EdgeType.MAJOR_SHAREHOLDER_OF,
        source_name="삼성물산㈜",
        source_corp_code="00149655",
        target_name=None,
        target_corp_code="00126380",
        rcept_no="20250311001085",
        fiscal_year="2025",
        as_of="20241231",
        source=Source.STRUCTURED,
        share_pct=pct,
        share_qty=qty,
    )


def test_same_share_count_different_denominator_is_not_a_contradiction():
    """실측: 삼성전자↔삼성물산은 같은 298,818,100주를 서로 다른 분모로 신고한다.

    「최대주주 현황」은 주식종류별(보통주) 기준 5.01%,
    「타법인 출자현황」은 총발행주식 기준 4.4%.
    지분율만 비교하면 우선주를 발행한 거의 모든 기업에서 가짜 모순이 쏟아진다.
    """
    by_target = _qty_edge(5.01, 298_818_100)
    by_holder = _qty_edge(4.4, 298_818_100)
    assert compare_scope(by_target, by_holder) is Verdict.AGREE


def test_genuinely_different_share_count_is_still_a_mismatch():
    """분모 보정이 진짜 불일치까지 덮으면 안 된다."""
    by_target = _qty_edge(5.01, 298_818_100)
    by_holder = _qty_edge(5.01, 250_000_000)
    assert compare_scope(by_target, by_holder) is Verdict.MISMATCH


def test_falls_back_to_pct_when_share_count_missing():
    a = _qty_edge(30.0, None)
    b = _qty_edge(25.0, None)
    assert compare_scope(a, b) is Verdict.MISMATCH


def test_share_qty_is_parsed_from_both_filings():
    sh = parse_major_shareholder(
        {
            "status": "000",
            "list": [
                {
                    "rcept_no": "20250311001085",
                    "corp_code": "00126380",
                    "stock_knd": "보통주",
                    "nm": "삼성물산㈜",
                    "trmend_posesn_stock_co": "298,818,100",
                    "trmend_posesn_stock_qota_rt": "5.01",
                    "stlm_dt": "2024-12-31",
                }
            ],
        }
    )[0]
    inv = parse_investment(
        {
            "status": "000",
            "list": [
                {
                    "rcept_no": "20250814002350",
                    "corp_code": "00149655",
                    "inv_prm": "삼성전자",
                    "trmend_blce_qy": "298,818,100",
                    "trmend_blce_qota_rt": "4.4",
                    "stlm_dt": "2024-12-31",
                }
            ],
        }
    )[0]
    assert sh.share_qty == inv.share_qty == 298_818_100
    assert sh.share_pct != inv.share_pct  # 분모가 달라 지분율은 어긋난다


# --- D6: 소계/합계 행이 개별 주주와 함께 합산됨 ------------------------------


def _sh_row(nm: str, pct: str, knd: str = "보통주") -> dict:
    return {
        "rcept_no": "20250318001131",
        "corp_code": "00161383",
        "stock_knd": knd,
        "nm": nm,
        "trmend_posesn_stock_qota_rt": pct,
        "stlm_dt": "2024-12-31",
    }


def test_aggregate_rows_are_not_shareholders():
    """실측: 응답은 개별 주주 사이에 nm='계' 요약 행을 섞어 준다.

    '계' 는 주주가 아니다. 엣지로 만들면 지분 합계가 정확히 두 배가 된다
    (티씨케이 50.4%+계 50.4%=100.8%, 삼성바이오로직스 74.35%x2=148.7%).
    """
    payload = {
        "status": "000",
        "list": [
            _sh_row("TOKAI CARBON CO.,LTD.", "50.4"),
            _sh_row("계", "50.4"),
            _sh_row("계", "-", knd="기타"),
            _sh_row("계", "50.4", knd="합계"),
        ],
    }
    edges = parse_major_shareholder(payload)
    assert [e.source_name for e in edges] == ["TOKAI CARBON CO.,LTD."]
    assert detect_grade_a(edges) == []


def test_spaced_person_names_are_kept():
    """실데이터에 '김 형 관' 처럼 공백이 낀 실명이 있다. 요약 행 판정에 걸리면 안 된다."""
    payload = {"status": "000", "list": [_sh_row("김 형 관", "0.00")]}
    assert [e.source_name for e in parse_major_shareholder(payload)] == ["김 형 관"]


# --- D7: 주식수 반올림 단위 차이 --------------------------------------------


def test_thousand_share_rounding_is_not_a_contradiction():
    """실측: 「타법인 출자현황」은 천주 단위로 반올림해 신고하는 경우가 있다.

    삼성전자 -> 삼성전기: 17,693,084 (정확) vs 17,693,000 (반올림).
    정확 일치로 비교하면 삼성 계열 전체가 모순으로 뜬다 (7건 관측).
    """
    a = _qty_edge(23.69, 17_693_084)
    b = _qty_edge(23.7, 17_693_000)
    assert compare_scope(a, b) is Verdict.AGREE


def test_rounding_up_case_also_agrees():
    """13,462,673 -> 13,463,000 처럼 올림된 사례도 흡수해야 한다."""
    assert compare_scope(_qty_edge(19.58, 13_462_673), _qty_edge(19.6, 13_463_000)) is Verdict.AGREE
    assert compare_scope(_qty_edge(5.1, 2_004_717), _qty_edge(5.1, 2_005_000)) is Verdict.AGREE


def test_rounding_tolerance_does_not_swallow_real_gaps():
    """반올림 보정이 진짜 차이까지 덮으면 검출기가 무의미해진다."""
    a = _qty_edge(5.01, 298_818_100)
    b = _qty_edge(5.01, 250_000_000)
    assert compare_scope(a, b) is Verdict.MISMATCH


# --- D9: 개별 주주 축에도 주식종류 통합 문제 --------------------------------


def test_share_classes_are_summed_before_cross_check():
    """실측: 한화 -> 한화솔루션 62,420,460(보통주) + 641,746(기타) = 63,062,206(통합).

    「최대주주 현황」은 종류별로 행이 나뉘고 「타법인 출자현황」은 종류 통합이다.
    종류별 행 하나씩만 맞대면 나머지 종류가 통째로 차이로 잡혀
    지주회사 계열 전체가 CONFLICT 로 뜬다 (실측 6건).
    """
    from dartweave.trust.crosscheck import CrossResult, cross_check_structured

    def sh(knd: str, qty: int, pct: float) -> RelationEdge:
        return RelationEdge(
            edge_type=EdgeType.MAJOR_SHAREHOLDER_OF,
            source_name="(주)한화",
            source_corp_code=None,
            target_name=None,
            target_corp_code="TGT",
            rcept_no="20250311000001",
            fiscal_year="2025",
            as_of="20241231",
            source=Source.STRUCTURED,
            share_pct=pct,
            share_qty=qty,
            stock_knd=knd,
        )

    inv = RelationEdge(
        edge_type=EdgeType.INVESTS_IN,
        source_name="",
        source_corp_code="HANWHA",
        target_name="한화솔루션",
        target_corp_code=None,
        rcept_no="20251218000270",
        fiscal_year="2025",
        as_of="20241231",
        source=Source.STRUCTURED,
        share_pct=36.15,
        share_qty=63_062_206,
    )

    results = cross_check_structured(
        [sh("보통주", 62_420_460, 36.31), sh("기타", 641_746, 24.92)],
        [inv],
        {"(주)한화": "HANWHA", "한화솔루션": "TGT"},
        {},
    )
    assert {r.status for r in results} == {CrossResult.CONFIRMED}


def test_summing_does_not_hide_a_real_gap():
    """합산이 진짜 차이까지 덮으면 검출기가 무의미해진다."""
    from dartweave.trust.crosscheck import CrossResult, cross_check_structured

    sh = RelationEdge(
        edge_type=EdgeType.MAJOR_SHAREHOLDER_OF,
        source_name="A", source_corp_code=None, target_name=None,
        target_corp_code="TGT", rcept_no="20250311000001", fiscal_year="2025",
        as_of="20241231", source=Source.STRUCTURED, share_pct=10.0,
        share_qty=1_000_000, stock_knd="보통주",
    )
    inv = RelationEdge(
        edge_type=EdgeType.INVESTS_IN, source_name="", source_corp_code="H",
        target_name="T", target_corp_code=None, rcept_no="r", fiscal_year="2025",
        as_of="20241231", source=Source.STRUCTURED, share_pct=5.0,
        share_qty=500_000,
    )
    results = cross_check_structured([sh], [inv], {"A": "H", "T": "TGT"}, {})
    assert results[0].status is CrossResult.CONFLICT
