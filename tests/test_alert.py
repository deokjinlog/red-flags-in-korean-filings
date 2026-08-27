from dartweave.screen.alert import BLIND_SPOTS, Alert, Evidence

GC = Evidence(hit=44, distressed=14, base_rate=3.94, sample=2333,
              as_of="20240630", lead_median_days=486, lead_min_days=92)


def test_rate_and_ratio_are_measured_not_asserted():
    assert round(GC.rate, 1) == 31.8
    assert round(GC.ratio, 1) == 8.1


def test_caveat_always_states_the_survivors():
    """걸린 것의 대부분은 아무 일도 없다 — 이 줄이 빠지면 경고가 과장된다."""
    assert "68%는 아무 일도 없었습니다" in GC.caveat()


def test_sentence_carries_lead_time():
    s = GC.sentence()
    assert "16개월" in s and "92일" in s


def test_single_base_date_is_disclosed():
    """기준시점 하나짜리를 여러 시점에서 확인한 것처럼 보이면 안 된다."""
    assert "기준시점 1개" in GC.provenance()
    assert "기준시점 4개에서 확인" in Evidence(
        hit=633, distressed=59, base_rate=3.94, sample=2333,
        as_of="20240630", bases=4).provenance()


def test_url_is_not_invented_without_a_filing():
    a = Alert("계속기업 경고", "감사인이 단 경고", "발견", "V. 감사의견", GC)
    assert a.url is None
    assert Alert("x", "y", "z", "w", GC, rcept_no="20240315000123").url.endswith(
        "rcpNo=20240315000123")


def test_blind_spots_name_the_price_gap():
    assert any("주가" in s for s in BLIND_SPOTS)
    assert any("33%" in s for s in BLIND_SPOTS)


def test_build_refuses_signals_without_measured_evidence():
    """근거 없는 경고를 만들 수 있으면, 언젠가 지어낸 숫자가 화면에 나간다."""
    from dartweave.screen.alert import build
    assert build("근거없는신호", "무언가") is None
    a = build("계속기업 경고", "2023 감사보고서 강조사항에 계속기업 불확실성")
    assert a is not None and a.evidence.hit == 44
    assert a.refutes and a.where and a.what


def test_measured_numbers_live_in_one_place():
    """리포트와 경고가 각자 숫자를 들고 있으면 한쪽만 갱신돼 조용히 갈라진다."""
    from dartweave.screen.alert import MEASURED
    assert round(MEASURED["결손금"].rate, 1) == 9.3
    assert MEASURED["결손금"].bases == 4          # 네 시점에서 확인
    assert MEASURED["계속기업 경고"].bases == 1    # 아직 한 시점


def test_every_measured_signal_carries_where_and_refutes():
    """경로가 비면 '봐야 한다' 는 알겠는데 어디를 여는지 모른다.
    반증조건이 비면 경고가 검증 가능한 주장이 아니라 감상문이 된다."""
    from dartweave.screen.alert import MEASURED, REFUTES, WHAT, WHERE
    for kind in MEASURED:
        assert WHAT.get(kind), kind
        assert WHERE.get(kind), kind
        assert REFUTES.get(kind), kind
