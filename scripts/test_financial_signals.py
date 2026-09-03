"""재무 신호를 구조 신호와 **같은 잣대로** 검정한다.

왜 이걸 하나:
  지분 구조 신호는 7종 전부 채택되지 않았다. 그러면 남는 질문은 하나다 —
  **잣대가 너무 빡센 건가, 아니면 구조에 정말 신호가 없는 건가.**
  재무 신호는 교과서적으로 부실을 예고한다고 알려져 있다. 같은 틀에 넣어보면
  안다. 재무가 통과하면 잣대는 멀쩡하고 구조에 신호가 없는 것이고,
  재무도 떨어지면 잣대가 너무 빡센 것이다.

같은 잣대란:
  · 시점 분리 — 재무는 T 이전 사업연도, 라벨은 T 이후 730일 실제 부실
  · 회사 단위 — 기준시점을 합치지 않는다 (같은 회사를 두 번 세면 p 가 부풀려진다)
  · 교란 통제 — 자산 규모 × 업종 교차, 설정 8개를 흔들고 **가장 보수적인 답**을 채택
  · 커버리지 — 재무를 확보한 상장사 전부. **그래프 소속은 요구하지 않는다.**

    처음엔 요구했다가 고쳤다. 감사의견 라벨에서 커버리지 편향(그래프 밖이 오히려
    문제가 적다)을 겪은 게 남아서 그대로 옮겼는데, 재무 신호에 지분 그래프 소속을
    요구할 이유가 없다. 그러면 **DART 타법인출자 API 의 연도별 수록 편차**가 표본을
    좌우한다 — 실측으로 2019·2020 사업연도는 2021년의 3분의 1도 안 준다(삼성전자
    타법인출자가 2021년 146행인데 2020년은 2행이다). 그래서 T=2021 기준시점의
    표본이 통째로 부족해져 전부 판정 불가로 나왔다.

사용:
    uv run python scripts/test_financial_signals.py
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import date
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from dartweave.screen.audit import (
    has_going_concern,
    normalize_opinion,
    rows_for_year,
)

from dartweave.db.asof import CensoredWindowError, events_after
from dartweave.screen.calendar import Due, due_within
from dartweave.signal.labels import is_adverse
from dartweave.signal.test import (
    Verdict,
    mantel_haenszel_ratio,
    stratified_permutation_test,
)
from test_isolation_controlled import GRID


SIGNALS_ORDER = ("완전자본잠식", "부분자본잠식", "자본잠식(완전+부분)", "영업손실",
                 "당기순손실", "결손금", "부채비율 200% 초과", "매출 감소",
                 "영업현금흐름 음수", "이자보상배율 1 미만",
                 # A축 — 이익의 질. 숫자 조작·좀비기업이 여기서 먼저 드러난다.
                 "이익-현금 괴리", "발생액 상위 25%", "재무CF 연명",
                 "이자보상배율<1 3년 연속", "매출채권+재고 급증",
                 # 학계·실무 모형에서 변수만 빌려온 것. 계수는 안 빌린다.
                 "현금 런웨이 1년 미만", "현금 런웨이 2년 미만", "재무CF 꺾임",
                 "이익잉여금/자산 하위 25%",
                 # 자금 캘린더 — 예측이 아니라 날짜와 금액의 뺄셈.
                 "2년 내 사채 만기 > 보유 현금", "2년 내 만기 사채에 풋옵션",
                 # 방향 — 상태가 같아도 어디로 가는지가 다르면 다른 회사다.
                 "이익잉여금 3년 악화", "영업이익 3년 악화",
                 # 감사 — 표에 안 나오고 문장으로만 있는 칸.
                 "감사 계속기업 경고", "감사 의견거절·한정",
                 "감사 경고 (거절·한정·계속기업)",
                 # E축 — 공시 행태. 재무를 안 보고도 되는 유일한 축이다.
                 "최근 3년 불성실공시", "최근 3년 불성실공시 2회 이상",
                 # D축 — 조달 이력. 점검표가 가장 무겁게 치는데 검정된 적이 없다.
                 "최근 3년 CB·BW 발행", "최근 3년 CB·BW 2회 이상",
                 # C축 — 오너 리스크. 내부자가 팔고 있나, 최대주주가 자주 바뀌나.
                 "내부자 매도", "최대주주 변경 최근 3년")


def _get(acc: dict, name: str) -> float | None:
    v = acc.get(name)
    return float(v) if v is not None else None


def interest_cost(cf: dict) -> float | None:
    """이자비용 — 실제로 나간 현금이 가장 곧다. 없으면 발생주의, 그것도 없으면 금융원가.

    금융원가를 마지막에 두는 이유: 이자 외 항목(외환차손·파생상품평가손실)이 섞여 있어
    이자보상배율을 실제보다 나쁘게 만든다.
    """
    for key in ("이자의지급", "이자비용", "금융원가"):
        v = cf.get(key)
        if v is not None and float(v) > 0:
            return float(v)
    return None


def features(
    acc: dict,
    prev: dict,
    cf: dict | None = None,
    prev_cf: dict | None = None,
    history: list[tuple[dict, dict]] | None = None,
    accrual_cut: float | None = None,
    retained_cut: float | None = None,
    due: Due | None = None,
    bond_count: int | None = None,
    insider: dict | None = None,
    audit: str | None = None,
    bad_disclosure: int | None = None,
) -> dict[str, bool | None]:
    """재무 신호 후보. 값이 없으면 None — 모르는 걸 '아니다' 로 세지 않는다."""
    equity, capital = _get(acc, "자본총계"), _get(acc, "자본금")
    debt, op = _get(acc, "부채총계"), _get(acc, "영업이익")
    net, retained = _get(acc, "당기순이익(손실)"), _get(acc, "이익잉여금")
    sales, sales_prev = _get(acc, "매출액"), _get(prev, "매출액")
    ocf = _get(cf or {}, "영업활동현금흐름")
    fcf = _get(cf or {}, "재무활동현금흐름")
    fcf_prev = _get(prev_cf or {}, "재무활동현금흐름")
    cash_on_hand = _get(cf or {}, "현금및현금성자산")
    assets = _get(acc, "자산총계")
    accrual = accrual_ratio(acc, cf)
    return {
        "완전자본잠식": None if equity is None else equity <= 0,
        "부분자본잠식": (None if equity is None or capital is None
                    else 0 < equity < capital),
        "자본잠식(완전+부분)": (None if equity is None or capital is None
                          else equity <= 0 or equity < capital),
        "영업손실": None if op is None else op < 0,
        "당기순손실": None if net is None else net < 0,
        "결손금": None if retained is None else retained < 0,
        "부채비율 200% 초과": (None if debt is None or equity is None or equity <= 0
                        else debt / equity > 2.0),
        "매출 감소": (None if sales is None or sales_prev is None or sales_prev <= 0
                  else sales < sales_prev),
        "영업현금흐름 음수": (None if not cf or cf.get("영업활동현금흐름") is None
                     else float(cf["영업활동현금흐름"]) < 0),
        # 영업이익으로 이자도 못 갚는가. 영업손실이면 정의상 못 갚는 것이라 True 다.
        "이자보상배율 1 미만": (None if not cf or op is None
                        or interest_cost(cf) is None
                        else op < interest_cost(cf)),

        # ── 이익의 질 ────────────────────────────────────────────────
        # 순이익은 나는데 영업현금은 나간다. 가공매출·밀어내기의 전형이고,
        # **임계가 없어서** 파라미터를 고를 여지가 없다.
        "이익-현금 괴리": (None if net is None or ocf is None
                     else net > 0 and ocf < 0),
        # 발생액 = 순이익 − 영업CF. 자산으로 나눠 규모를 지운다. 상위 몇 %를
        # 볼지는 우리가 고른 값이라 스윕 대상이다(accrual_cut).
        "발생액 상위 25%": (None if accrual_cut is None or accrual is None
                      else accrual >= accrual_cut),
        # 영업에서 현금이 나가는데 차입·증자로 버틴다 = 조달이 끊기면 죽는다.
        "재무CF 연명": (None if ocf is None or fcf is None
                    else ocf < 0 and fcf > 0),
        # 3년 내리 이자도 못 갚으면 한계기업(좀비)이다. 한 해 적자보다 무겁다.
        "이자보상배율<1 3년 연속": _zombie(history),
        # 매출은 느는데 현금이 안 들어온다 — 매출채권·재고가 매출보다 빨리 는다.
        # ⚠️ 매출채권·재고는 주요계정이 아니라 **전체 재무제표** 쪽에 있다.
        # acc(fin_by_year)에서 찾으면 전 기업이 None 이 되어 조용히 0사로 나온다.
        "매출채권+재고 급증": _working_capital_spike(
            cf or {}, prev_cf or {}, sales, sales_prev),

        # ── 남의 모형에서 변수만 빌려온 것 ──────────────────────────
        # 회사는 적자라서 죽는 게 아니라 **현금이 마르면** 죽는다. 같은 적자라도
        # 남은 시간이 다르면 다른 이야기고, 우리 신호 8종은 그걸 안 본다.
        #
        # 런웨이(년) = 현금및현금성자산 ÷ 연간 영업CF 소진액. 임계 "1년" 은
        # 우리가 고른 값이라 2년도 같이 낸다 — 하나만 내면 고른 티가 안 난다.
        # 안 태우는 회사(ocf ≥ 0)는 False 다. 모르는 게 아니라 해당이 아니다.
        "현금 런웨이 1년 미만": (None if ocf is None or cash_on_hand is None
                        else ocf < 0 and cash_on_hand < -ocf),
        "현금 런웨이 2년 미만": (None if ocf is None or cash_on_hand is None
                        else ocf < 0 and cash_on_hand < -2 * ocf),
        # 재무CF 가 (+) 에서 (−) 로 꺾였다 = 빌려주던 쪽이 발을 뺐다.
        # 이미 있는 "재무CF 연명"(ocf<0 이면서 fcf>0)과 다르다 — 저건 **아직
        # 대주는 중**이고 이건 **끊긴 해**다.
        "재무CF 꺾임": (None if fcf is None or fcf_prev is None
                    else fcf_prev > 0 and fcf < 0),
        # Altman Z 의 X2 다. 계수는 안 빌리고 변수만 빌린다 — 1968년 미국
        # 제조업 66개사에서 뽑은 가중치를 한국 상장사에 그대로 얹으면, 실측으로
        # 바꿔 놓은 판정선을 다시 남의 가정으로 되돌리는 것이다.
        #
        # 우리가 이미 채택한 "결손금"(이익잉여금 < 0)의 **규모로 나눈** 판이라,
        # 둘이 같은 신호인지 다른 신호인지가 여기서 갈린다.
        "이익잉여금/자산 하위 25%": (None if retained_cut is None or retained is None
                           or not assets or assets <= 0
                           else retained / assets <= retained_cut),

        # ── 방향 ────────────────────────────────────────────────────
        # 상태가 같아도 어디로 가는지가 다르면 다른 회사다. 실측으로 결손금 안에서
        # 갈린다 — 결손금+악화 408사 10.3% vs 결손금+개선 86사 1.2%, 여덟 배.
        #
        # ⚠️ 영업이익 방향은 **안 듣는다**(영업손실+개선 7.8% > 악화 6.3%). 바닥에서
        #    조금 올라온 것도 개선으로 잡히기 때문이다. 그래서 둘을 따로 낸다 —
        #    "방향" 을 한 덩어리로 묶으면 안 듣는 쪽이 듣는 쪽을 희석시킨다.
        "이익잉여금 3년 악화": _worsening(history, "이익잉여금"),
        "영업이익 3년 악화": _worsening(history, "영업이익"),

        # ── 자금 캘린더 ─────────────────────────────────────────────
        # 갚아야 할 돈이 가진 돈보다 많은가. 계수도 임계도 없는 뺄셈이다.
        # 사채가 없는 회사는 0 > 현금 이 거짓이라 자동으로 False 다.
        "2년 내 사채 만기 > 보유 현금": (None if due is None or cash_on_hand is None
                             else due.amount > cash_on_hand),
        # 풋이 붙었으면 만기보다 **이르게** 청구될 수 있다. 청구 가능일은 공시
        # 본문의 산문이라 못 뽑으니, 붙었는지만 따로 낸다.
        "2년 내 만기 사채에 풋옵션": None if due is None else due.has_put,

        # ── 조달 이력 ────────────────────────────────────────────────
        # 발행 건수는 목록 API 만으로 나온다. **0건과 '모른다' 는 다르다** —
        # 목록을 안 받은 상태면 None 이어야지 0 이면 안 된다.
        "최근 3년 CB·BW 발행": None if bond_count is None else bond_count >= 1,
        "최근 3년 CB·BW 2회 이상": None if bond_count is None else bond_count >= 2,

        # ── 오너 리스크 ─────────────────────────────────────────────
        # 임원·주요주주 소유상황보고의 증감 칸이 음수면 팔았다는 뜻이다.
        # 보고가 아예 없는 회사는 '안 팔았다' 가 아니라 **모른다** 다.
        # ⚠️ 지금은 항상 None 이다 — `elestock.json` 이 bsns_year 를 무시하고 현재
        # 이력만 줘서 T 이전 접수 보고가 0건이다. 정의는 남겨두지만 데이터가 시점
        # 분리를 못 해 검정이 불가능하다. `collect_insider` 참조.
        "내부자 매도": (None if not insider or not insider.get("insider")
                   else any((x.get("delta") or 0) < 0
                            for x in insider["insider"])),
        # 최대주주가 최근 3년에 바뀌었나. 변경일로 자른다 — 사업연도로만 자르면
        # 10년 전 변경 이력까지 딸려 온다.
        "최대주주 변경 최근 3년": (None if insider is None
                        else bool(insider.get("_owner_recent"))),

        # ── 감사 ────────────────────────────────────────────────────
        # 부실 상장폐지 154건 중 83건(54%)이 감사의견이다. 그런데 그 경고는 표가
        # 아니라 강조사항 칸의 문장이라 대개 안 읽힌다.
        #
        # `audit` 은 'adverse'(의견거절·한정) / 'concern'(계속기업 경고) /
        # 'none'(경고 없음) / None(감사보고서를 못 받음). **None 을 False 로 세면
        # 안 된다** — 못 받은 것과 경고가 없는 것은 다르다. 2023년 기준 상장사
        # 2,581사만 감사의견을 갖고 있다.
        "감사 계속기업 경고": (None if audit is None else audit == "concern"),
        "감사 의견거절·한정": (None if audit is None else audit == "adverse"),
        "감사 경고 (거절·한정·계속기업)": (None if audit is None
                              else audit in ("adverse", "concern")),

        # ── E축 · 공시 행태 ──────────────────────────────────────────
        # 재무제표가 아니라 **회사가 공시를 어떻게 다루는가**를 본다. 로드맵에 있었지만
        # 한 번도 못 쟀던 축이고, DART OpenAPI 에는 없다(거래소 소관).
        #
        # 여기서 None 이 없는 게 중요하다. 불성실공시 지정은 전수 명단이라 명단에
        # 없으면 **지정된 적 없다**는 뜻이다 — 감사의견처럼 "못 받았다" 가 아니다.
        # (다만 corp_code 를 못 붙인 5% 는 조용히 False 가 된다. 신호를 약하게
        #  만드는 방향이라 과장은 아니다.)
        "최근 3년 불성실공시": (None if bad_disclosure is None
                        else bad_disclosure >= 1),
        "최근 3년 불성실공시 2회 이상": (None if bad_disclosure is None
                              else bad_disclosure >= 2),
    }


# 15% 는 우리가 고른 값이다. 회계 변경·일회성으로 몇 %는 늘 흔들려서 그 아래를
# "그대로" 로 둔다. 임계를 쓰는 신호는 스윕 대상이라는 규율이 여기도 걸린다.
_DRIFT = 0.15


def _worsening(history: list[tuple[dict, dict]] | None,
               account: str) -> bool | None:
    """3년 전 대비 그만큼 나빠졌나. 한 해라도 모르면 판정하지 않는다.

    `history` 는 [당해, 전년, 전전년] 순이다. 분모에 절대값을 쓰는 건 이익잉여금이
    음수인 회사 때문이다 — 음수가 더 음수가 되는 걸 "증가" 로 읽으면 뒤집힌다.
    """
    if not history or len(history) < 3:
        return None
    now = _get(history[0][0], account)
    then = _get(history[2][0], account)
    if now is None or then is None or then == 0:
        return None
    return (now - then) / abs(then) < -_DRIFT


def accrual_ratio(acc: dict, cf: dict | None) -> float | None:
    """발생액 비율 = (당기순이익 − 영업활동현금흐름) ÷ 자산총계.

    클수록 "장부 이익이 현금으로 안 들어온다" 는 뜻이다. 자산으로 나누는 이유는
    큰 회사가 자동으로 상위에 오르는 걸 막기 위해서다 — 우리가 규모를 층화로
    통제하는 것과 같은 이유고, 여기서는 지표 정의 안에서 지운다.
    """
    net = _get(acc, "당기순이익(손실)")
    assets = _get(acc, "자산총계")
    ocf = _get(cf or {}, "영업활동현금흐름")
    if net is None or ocf is None or not assets or assets <= 0:
        return None
    return (net - ocf) / assets


def _zombie(history: list[tuple[dict, dict]] | None) -> bool | None:
    """3개 연도 전부 영업이익 < 이자비용인가. 한 해라도 모르면 판정하지 않는다."""
    if not history or len(history) < 3:
        return None
    verdicts = []
    for acc, cf in history[:3]:
        op = _get(acc, "영업이익")
        interest = interest_cost(cf or {})
        if op is None or interest is None:
            return None
        verdicts.append(op < interest)
    return all(verdicts)


def _working_capital_spike(
    cf: dict, prev_cf: dict, sales: float | None, sales_prev: float | None
) -> bool | None:
    """매출채권+재고가 매출보다 빨리 늘었는가.

    매출이 줄었는데 운전자본이 늘어난 경우도 걸린다 — 그쪽이 오히려 더 나쁘다.
    """
    now = [_get(cf, k) for k in ("매출채권", "재고자산")]
    was = [_get(prev_cf, k) for k in ("매출채권", "재고자산")]
    if any(v is None for v in now + was) or sales is None or sales_prev is None:
        return None
    wc_now, wc_was = sum(now), sum(was)
    if wc_was <= 0 or sales_prev <= 0:
        return None
    return (wc_now / wc_was) > (sales / sales_prev) * 1.2


def cells_for(pool, assets, industry, label, is_signal, n_strata, digits):
    """자산 층 × 업종 교차 셀. 신호 여부는 넘겨받은 술어로 가른다."""
    ordered = sorted(pool, key=lambda c: assets[c])
    size = max(1, len(ordered) // n_strata)
    buckets: dict[tuple, list[str]] = defaultdict(list)
    for i in range(n_strata):
        chunk = ordered[i * size:] if i == n_strata - 1 else ordered[i * size:(i + 1) * size]
        for c in chunk:
            buckets[(i, industry[c][:digits] if digits else "")].append(c)
    return [([c in label for c in codes if is_signal(c)],
             [c in label for c in codes if not is_signal(c)])
            for codes in buckets.values()]


def sweep(pool, assets, industry, label, is_signal, runs):
    """설정 8개를 흔들고 (통제없음 배율, 최보수 배율, 최보수 p, 유의한 설정 수) 를 낸다."""
    rows = []
    for n_strata, digits in GRID:
        st = cells_for(pool, assets, industry, label, is_signal, n_strata, digits)
        r = stratified_permutation_test(st, runs=runs)
        if r.verdict is Verdict.TOO_FEW:
            return None, r
        rows.append((mantel_haenszel_ratio(st), r.p_value, r.verdict))
    return rows, None


def _owner_views(insider: dict, as_of: str):
    """오너 리스크를 **날짜로** 자른다 — 사업연도 키로는 안 된다.

    `elestock` 은 사업연도로 묶여 오지만 각 보고의 접수일은 그 안에 있지 않다.
    실측으로 2023 사업연도 자료에 접수일 2024-10-02 인 보고가 들어 있었고,
    T=2024-06-30 기준으로 그건 아직 모르는 정보다. 연도 키만 쓰면 **미래를
    훔쳐보거나(늦은 보고를 당겨쓰거나) 통째로 비어버린다** — 처음엔 후자였고
    '내부자 매도 해당 0사' 로 조용히 나왔다.

    그래서 수집한 모든 연도를 한데 모아 날짜로 자른다. 최대주주 변경은 최근 3년
    창으로 본다 — 전체 이력을 세면 거의 전 기업이 걸린다.
    """
    cut3 = str(int(as_of[:4]) - 3) + as_of[4:]
    pooled: dict[str, dict[str, list]] = {}
    for rows in insider.values():
        for code, rec in rows.items():
            slot = pooled.setdefault(code, {"insider": [], "owner_change": []})
            slot["insider"].extend(rec.get("insider") or [])
            slot["owner_change"].extend(rec.get("owner_change") or [])

    def view(code: str) -> dict | None:
        rec = pooled.get(code)
        if rec is None:
            return None
        seen = {(x.get("date"), x.get("who"), x.get("delta")) for x in rec["insider"]}
        return {
            "insider": [{"date": d, "who": w, "delta": v} for d, w, v in seen
                        if d and d <= as_of],
            "_owner_recent": any(cut3 <= (c.get("on") or "") <= as_of
                                 for c in rec["owner_change"]),
        }

    return view


def build_features(
    as_of: str,
    *,
    fin_path: str = "data/fin_by_year.json",
    cash_path: str = "data/cashflow_by_year.json",
    bonds_path: str = "data/bond_filings.json",
    terms_path: str = "data/bond_terms.json",
    insider_path: str = "data/insider.json",
    audit_path: str = "data/audit_opinions.json",
    bad_path: str = "data/kind_bad_disclosure.csv",
) -> tuple[dict[str, dict], dict[str, float]]:
    """기준시점 하나의 (회사 → 신호 여부, 회사 → 자산총계).

    `main` 안에 있던 걸 빼냈다 — 개수 검정 쪽에서 같은 계산을 다시 쓰는데,
    두 벌로 두면 신호 정의가 갈라진다. 실제로 `check_company` 와 `ask` 가
    그렇게 갈라진 적이 있다.
    """
    read = lambda f: (json.loads(Path(f).read_text(encoding="utf-8"))  # noqa: E731
                      if Path(f).exists() else {})
    fin, cash, bonds = read(fin_path), read(cash_path), read(bonds_path)
    terms = read(terms_path)
    insider = read(insider_path)
    audit_book = read(audit_path)
    year = str(int(as_of[:4]) - 1)
    acc_now, acc_prev = fin.get(year, {}), fin.get(str(int(year) - 1), {})
    cash_now, cash_prev = cash.get(year, {}), cash.get(str(int(year) - 1), {})

    window = {str(int(as_of[:4]) - k) for k in (1, 2, 3)}
    counts: dict[str, int] = {}
    for v in bonds.values():
        if v.get("corp_code") and v.get("date", "")[:4] in window:
            counts[v["corp_code"]] = counts.get(v["corp_code"], 0) + 1

    # 자금 캘린더 — 기준일 이전에 **발행**된 사채만 모은다. 조항은 접수번호로
    # 붙는다(bond_terms 는 bond_filings 의 부분집합이라 조항 없는 건은 빠진다).
    base = date(int(as_of[:4]), int(as_of[4:6]), int(as_of[6:8]))
    by_corp: dict[str, list[dict]] = defaultdict(list)
    for rcept, meta in bonds.items():
        code, filed = meta.get("corp_code"), meta.get("date", "")
        row = terms.get(rcept)
        if code and row and filed and filed <= as_of:
            by_corp[code].append(row)
    due_of = {c: due_within(rows, base, years=2) for c, rows in by_corp.items()}

    # 자금 캘린더 — 기준일 이전에 **발행**된 사채만 모은다. 조항은 접수번호로
    # 붙는다(bond_terms 는 bond_filings 의 부분집합이라 조항 없는 건은 빠진다).
    base = date(int(as_of[:4]), int(as_of[4:6]), int(as_of[6:8]))
    by_corp: dict[str, list[dict]] = defaultdict(list)
    for rcept, meta in bonds.items():
        code, filed = meta.get("corp_code"), meta.get("date", "")
        row = terms.get(rcept)
        if code and row and filed and filed <= as_of:
            by_corp[code].append(row)
    due_of = {c: due_within(rows, base, years=2) for c, rows in by_corp.items()}

    # 감사의견은 재무와 같은 사업연도를 쓴다 — as_of 20240630 이면 2023 사업보고서다
    # (2024-03 제출). 한 요청에 당기·전기·전전기가 함께 오므로 2021~2023 이 이미 있다.
    audit_of: dict[str, str] = {}
    for code, rows in audit_book.items():
        got = rows_for_year(rows or [], int(year))
        if not got:
            continue
        # 나쁜 쪽부터 본다. 의견거절 본문에도 계속기업 이야기가 들어 있어서,
        # 경고를 먼저 보면 의견거절이 계속기업 경고로 내려앉는다.
        if any(normalize_opinion(r.get("opinion")).is_adverse for r in got):
            audit_of[code] = "adverse"
        elif any(has_going_concern(r.get("emphasis")) for r in got):
            audit_of[code] = "concern"
        else:
            audit_of[code] = "none"

    # 불성실공시 — 기준일 **이전** 3년만 센다. 지정일이 그대로 시점 게이트다.
    # 명단이 없으면 전부 None 으로 둔다(파일이 없는 것과 지정이 없는 것은 다르다).
    bad_of: dict[str, int] | None = None
    bad_file = Path(bad_path)
    if bad_file.exists():
        import csv as _csv

        cc_map = read("data/corpcode.json")
        window_from = str(int(as_of[:4]) - 3) + as_of[4:]
        counts_bad: dict[str, int] = defaultdict(int)
        with bad_file.open(encoding="utf-8") as fh:
            for row in _csv.DictReader(fh):
                if row["is_signal"] != "1":
                    continue
                code = cc_map.get(row["corp_name"])
                if code and window_from < row["date"] <= as_of:
                    counts_bad[code] += 1
        bad_of = dict(counts_bad)

    years3 = [year, str(int(year) - 1), str(int(year) - 2)]
    hist = lambda c: [(fin.get(y, {}).get(c) or {}, cash.get(y, {}).get(c) or {})
                      for y in years3]
    pool = [c for c in acc_now if acc_now[c].get("자산총계")]
    accruals = sorted(v for v in (accrual_ratio(acc_now[c], cash_now.get(c, {}))
                                  for c in pool) if v is not None)
    cut = accruals[int(len(accruals) * 0.75)] if len(accruals) >= 20 else None
    ratios = sorted(float(acc_now[c]["이익잉여금"]) / float(acc_now[c]["자산총계"])
                    for c in pool
                    if acc_now[c].get("이익잉여금") is not None
                    and float(acc_now[c]["자산총계"]) > 0)
    r_cut = ratios[int(len(ratios) * 0.25)] if len(ratios) >= 20 else None
    owner_of = _owner_views(insider, as_of)

    feats = {c: features(acc_now[c], acc_prev.get(c, {}), cash_now.get(c, {}),
                         cash_prev.get(c, {}), hist(c), cut, r_cut,
                         due_of.get(c, Due(0.0, 0, 0)) if terms else None,
                         counts.get(c, 0) if bonds else None, owner_of(c),
                         audit_of.get(c),
                         (bad_of.get(c, 0) if bad_of is not None else None))
             for c in pool}
    return feats, {c: float(acc_now[c]["자산총계"]) for c in pool}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--db", default="sqlite:///data/timeseries.db")
    p.add_argument("--as-of", default="20220630,20230630")
    p.add_argument("--within-days", type=int, default=730)
    p.add_argument("--fin", default="data/fin_by_year.json")
    p.add_argument("--cash", default="data/cashflow_by_year.json")
    p.add_argument("--bonds", default="data/bond_filings.json")
    p.add_argument("--terms", default="data/bond_terms.json")
    p.add_argument("--insider", default="data/insider.json")
    p.add_argument("--industry", default="data/industry.json")
    p.add_argument("--include-warning", action="store_true",
                   help="관리종목 지정(부실 사유)도 라벨로 센다. 표본이 두 배라 늘 "
                        "유리해 보이므로 기본값은 꺼짐 — 켜면 보고서에 적어야 한다.")
    p.add_argument("--runs", type=int, default=8000)
    p.add_argument("--out", default="data/signal_results.json",
                   help="판정 결과를 기계가 읽을 수 있게 남긴다 — 손으로 옮기면 틀린다")
    args = p.parse_args(argv)

    read = lambda f: json.loads(Path(f).read_text(encoding="utf-8"))  # noqa: E731
    fin = read(args.fin)
    cash = read(args.cash) if Path(args.cash).exists() else {}
    bonds = read(args.bonds) if Path(args.bonds).exists() else {}
    insider = read(args.insider) if Path(args.insider).exists() else {}
    industry = {k: str(v) for k, v in read(args.industry).items() if v}
    engine = create_engine(args.db)

    verdicts: dict[str, list[str]] = defaultdict(list)
    results: list[dict] = []
    for T in [x.strip() for x in args.as_of.split(",") if x.strip()]:
        year = str(int(T[:4]) - 1)              # T 시점에 이미 공시된 마지막 사업연도
        with Session(engine) as s:
            try:
                events = events_after(s, T, within_days=args.within_days)
            except CensoredWindowError as e:
                # 관측 창이 모자란 기준시점 하나 때문에 전체 실행을 죽이지 않는다.
                # 대신 **조용히 포함시키지도 않는다** — 그게 배율 비교를 어긋나게 한다.
                print(f"\n{'=' * 74}\nT={T} 건너뜀 — {e}")
                continue
        label = {e.corp_code for e in events
             if is_adverse(e.event_type, include_warning=args.include_warning)}
        # 신호 정의는 `build_features` 한 곳에만 둔다. 여기에 같은 계산을 두 벌로
        # 갖고 있었는데, 인자를 하나 늘리자마자 위치 인자가 어긋나 조용히 다른 값이
        # 들어갔다 — 갈라진 정의는 이렇게 티가 안 나게 틀린다.
        feats, assets = build_features(
            T, fin_path=args.fin, cash_path=args.cash,
            bonds_path=args.bonds, terms_path=args.terms,
            insider_path=args.insider)
        pool = sorted(c for c in feats if c in industry)

        print(f"\n{'=' * 74}\nT={T} · {year}년 재무 · 대상 {len(pool):,}사 "
              f"· 이후 {args.within_days}일 부실 {len(label & set(pool))}사\n")
        print(f"  {'신호':16s} {'해당':>6s} {'부실률':>7s} {'통제없음':>8s} "
              f"{'최보수':>7s} {'p':>8s}  판정")
        for name in SIGNALS_ORDER:
            hit = [c for c in pool if feats[c].get(name)]
            if len(hit) < 30:
                print(f"  {name:16s} {len(hit):>6,}  — 해당 기업이 적어 판정 보류")
                continue
            events_in = sum(1 for c in hit if c in label)
            rows, too_few = sweep(pool, assets, industry, label,
                                  lambda c: bool(feats[c].get(name)), args.runs)
            if too_few is not None:
                print(f"  {name:16s} {len(hit):>6,} {events_in / len(hit) * 100:6.2f}%"
                      f"   판정 불가 — 신호군 부실 {events_in}건")
                continue
            plain = rows[0][0]
            # **두 가지 "가장 보수적" 을 따로 쓴다.**
            #   채택 여부  p 가 가장 큰 설정 — "제일 안 유의한 설정에서도 유의한가"
            #   보고 배율  배율이 가장 작은 설정 — 이건 순열과 무관해 결정적이다
            # 하나로 묶었더니 p 가 순열 추정이라 실행마다 뽑히는 설정이 바뀌고,
            # 보고 배율이 흔들렸다(영업손실 ×1.96 ↔ ×2.14). 근거 숫자가 실행마다
            # 다르면 문서에 적을 수 없다.
            worst = max(rows[1:], key=lambda x: x[1])
            floor = min(rows[1:], key=lambda x: x[0])
            sup = sum(1 for x in rows[1:] if x[2] is Verdict.SUPPORTED)
            ok = worst[2] is Verdict.SUPPORTED
            verdicts[name].append("채택" if ok else "탈락")
            results.append({"signal": name, "as_of": T, "n": len(hit),
                            "events": events_in, "plain_ratio": plain,
                            "ratio": floor[0], "p_value": worst[1],
                            "verdict": "채택" if ok else "탈락",
                            "settings_supported": sup})
            print(f"  {name:16s} {len(hit):>6,} {events_in / len(hit) * 100:6.2f}% "
                  f"×{plain:7.2f} ×{floor[0]:6.2f} {worst[1]:8.4f}  "
                  f"{'채택' if ok else '탈락'} ({sup}/7)")

    Path(args.out).write_text(json.dumps(results, ensure_ascii=False, indent=1),
                              encoding="utf-8")
    n_dates = len([x for x in args.as_of.split(",") if x.strip()])
    print(f"\n{'=' * 74}\n기준시점 {n_dates}개 **전부**에서 채택된 신호:")
    # 한 시점이라도 판정을 못 했으면 '전부 채택' 이 아니다 — 보류를 통과로 세지 않는다.
    always = [k for k, v in verdicts.items() if len(v) == n_dates and set(v) == {"채택"}]
    print("  " + (", ".join(always) if always else "없음"))
    mixed = [k for k, v in verdicts.items() if len(set(v)) > 1]
    if mixed:
        print(f"  시점에 따라 갈린 신호: {', '.join(mixed)}")
    partial = [k for k, v in verdicts.items()
               if len(v) < n_dates and set(v) == {"채택"}]
    if partial:
        print(f"  판정이 난 시점에서는 전부 채택이지만 시점 수가 모자란 신호: "
              f"{', '.join(f'{k}({len(verdicts[k])}/{n_dates})' for k in partial)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
