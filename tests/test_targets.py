import pytest

from dartweave.dart.company import CompanyInfo
from dartweave.select.targets import IndustryFilter, select_targets


def _c(code, name, induty, cls="Y"):
    return CompanyInfo(code, name, "000000", cls, induty, None, None)


COMPANIES = [
    _c("001", "반도체소재", "20119"),
    _c("002", "반도체제조", "26110"),
    _c("003", "제빵회사", "10711"),
    _c("004", "장비회사", "29271"),
    _c("005", "비상장반도체", "26110", cls="N"),
]


def test_selects_by_industry_prefix():
    f = IndustryFilter(prefixes=["261"], manual_add={}, manual_exclude=set())
    picked = select_targets(COMPANIES, f)
    assert {p.corp_code for p in picked} == {"002", "005"}


def test_manual_add_requires_reason():
    with pytest.raises(ValueError, match="사유"):
        IndustryFilter(prefixes=["261"], manual_add={"001": ""}, manual_exclude=set())


def test_manual_add_included_with_reason_recorded():
    f = IndustryFilter(
        prefixes=["261"],
        manual_add={"004": "반도체 장비 — 업종코드가 기계로 분류되어 자동필터 누락"},
        manual_exclude=set(),
    )
    picked = {p.corp_code: p for p in select_targets(COMPANIES, f)}
    assert "004" in picked
    assert "자동필터 누락" in picked["004"].reason


def test_auto_selection_also_records_reason():
    f = IndustryFilter(prefixes=["261"], manual_add={}, manual_exclude=set())
    picked = {p.corp_code: p for p in select_targets(COMPANIES, f)}
    assert picked["002"].reason.startswith("업종코드")


def test_manual_exclude_wins_over_auto():
    f = IndustryFilter(prefixes=["261"], manual_add={}, manual_exclude={"005"})
    assert {p.corp_code for p in select_targets(COMPANIES, f)} == {"002"}
