from dartweave.screen.audit import rows_for_year, term_year


def test_recovers_year_from_term_label():
    """stlm_dt 는 세 기수에 같은 값이 붙어서 연도로 못 쓴다 — 기수로 되살린다."""
    assert term_year("제38기(당기)", 2023) == 2023
    assert term_year("제37기(전기)", 2023) == 2022
    assert term_year("제36기(전전기)", 2023) == 2021


def test_longest_label_wins():
    """'전기' 를 먼저 보면 '전전기' 가 전기로 읽힌다 — 의견 정규화와 같은 함정."""
    assert term_year("제36기(전전기)", 2023) != 2022


def test_unlabelled_term_yields_no_year():
    assert term_year("-", 2023) is None
    assert term_year("", 2023) is None


def test_selects_only_the_asked_year():
    recs = [
        {"term": "제38기(당기)", "opinion": "한정"},
        {"term": "제37기(전기)", "opinion": "적정"},
        {"term": "제36기(전전기)", "opinion": "적정"},
    ]
    assert [r["opinion"] for r in rows_for_year(recs, 2023)] == ["한정"]
    assert [r["opinion"] for r in rows_for_year(recs, 2021)] == ["적정"]


def test_stored_year_wins_over_term():
    """새 수집본은 year 를 갖고 있다 — 되살리기보다 그쪽을 믿는다."""
    recs = [{"term": "제38기(당기)", "year": 2020, "opinion": "적정"}]
    assert rows_for_year(recs, 2020) == recs
    assert rows_for_year(recs, 2023) == []
