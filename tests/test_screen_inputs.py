"""검사 입력 로딩 — 두 도구가 어긋나지 않게 한 곳에 모은 것."""
import json

from dartweave.screen.inputs import Financials, load_financials


def _write(tmp_path, fin, cash):
    f, c = tmp_path / "fin.json", tmp_path / "cash.json"
    f.write_text(json.dumps(fin, ensure_ascii=False), encoding="utf-8")
    c.write_text(json.dumps(cash, ensure_ascii=False), encoding="utf-8")
    return {"fin_path": f, "cash_path": c}


def test_picks_the_latest_year_that_has_retained_earnings(tmp_path):
    paths = _write(tmp_path, {
        "2022": {"A": {"이익잉여금": -100.0, "영업이익": 5.0}},
        "2023": {"A": {"영업이익": 9.0}},          # 이익잉여금이 없는 해는 건너뛴다
    }, {})
    got = load_financials("A", **paths)
    assert got.fiscal_year == "2022" and got.retained_earnings == -100.0


def test_interest_prefers_cash_paid(tmp_path):
    paths = _write(tmp_path,
                   {"2023": {"A": {"이익잉여금": 1.0}}},
                   {"2023": {"A": {"금융원가": 9.0, "이자의지급": 4.0}}})
    assert load_financials("A", **paths).interest_cost == 4.0


def test_missing_company_returns_empty_not_zero(tmp_path):
    """없는 회사를 0 으로 채우면 '흑자·무이자' 인 것처럼 걸리지 않는다."""
    paths = _write(tmp_path, {"2023": {"A": {"이익잉여금": 1.0}}}, {})
    got = load_financials("없는회사", **paths)
    assert got == Financials()
    assert got.retained_earnings is None and got.fiscal_year == ""


def test_missing_files_are_not_an_error(tmp_path):
    got = load_financials("A", fin_path=tmp_path / "x.json", cash_path=tmp_path / "y.json")
    assert got == Financials()


def test_cashflow_is_optional(tmp_path):
    """현금흐름을 안 받은 상태에서도 재무 신호는 실려야 한다."""
    paths = _write(tmp_path, {"2023": {"A": {"이익잉여금": -5.0, "영업이익": -1.0}}}, {})
    got = load_financials("A", **paths)
    assert got.retained_earnings == -5.0
    assert got.operating_cashflow is None and got.interest_cost is None


def test_both_tools_use_the_shared_loader():
    """두 도구가 각자 구현하면 또 어긋난다 — 실제로 한 번 어긋난 적이 있다.

    ask.py 는 재무를 아예 안 물려서, "사도 되나" 라는 질문에 검정에서 떨어진 구조
    정보만 답하고 통과한 재무는 빼놓는 상태로 한동안 돌았다.
    """
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "scripts"
    for name in ("check_company.py", "ask.py"):
        body = (root / name).read_text(encoding="utf-8")
        assert "from dartweave.screen.inputs import load_financials" in body, name
        assert "load_financials(code)" in body, name
        # 각자 재무 파일을 다시 파싱하면 그게 어긋남의 시작이다.
        assert "fin_by_year.json" not in body, name
        assert "cashflow_by_year.json" not in body, name
