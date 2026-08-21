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
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from dartweave.db.asof import CensoredWindowError, events_after
from dartweave.signal.labels import is_distress
from dartweave.signal.test import (
    Verdict,
    mantel_haenszel_ratio,
    stratified_permutation_test,
)
from test_isolation_controlled import GRID


SIGNALS_ORDER = ("완전자본잠식", "부분자본잠식", "자본잠식(완전+부분)", "영업손실",
                 "당기순손실", "결손금", "부채비율 200% 초과", "매출 감소",
                 "영업현금흐름 음수", "이자보상배율 1 미만")


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


def features(acc: dict, prev: dict, cf: dict | None = None) -> dict[str, bool | None]:
    """재무 신호 후보. 값이 없으면 None — 모르는 걸 '아니다' 로 세지 않는다."""
    equity, capital = _get(acc, "자본총계"), _get(acc, "자본금")
    debt, op = _get(acc, "부채총계"), _get(acc, "영업이익")
    net, retained = _get(acc, "당기순이익(손실)"), _get(acc, "이익잉여금")
    sales, sales_prev = _get(acc, "매출액"), _get(prev, "매출액")
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
    }


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


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--db", default="sqlite:///data/timeseries.db")
    p.add_argument("--as-of", default="20220630,20230630")
    p.add_argument("--within-days", type=int, default=730)
    p.add_argument("--fin", default="data/fin_by_year.json")
    p.add_argument("--cash", default="data/cashflow_by_year.json")
    p.add_argument("--industry", default="data/industry.json")
    p.add_argument("--runs", type=int, default=8000)
    args = p.parse_args(argv)

    read = lambda f: json.loads(Path(f).read_text(encoding="utf-8"))  # noqa: E731
    fin = read(args.fin)
    cash = read(args.cash) if Path(args.cash).exists() else {}
    industry = {k: str(v) for k, v in read(args.industry).items() if v}
    engine = create_engine(args.db)

    verdicts: dict[str, list[str]] = defaultdict(list)
    for T in [x.strip() for x in args.as_of.split(",") if x.strip()]:
        year = str(int(T[:4]) - 1)              # T 시점에 이미 공시된 마지막 사업연도
        acc_now, acc_prev = fin.get(year, {}), fin.get(str(int(year) - 1), {})
        cash_now = cash.get(year, {})
        with Session(engine) as s:
            try:
                events = events_after(s, T, within_days=args.within_days)
            except CensoredWindowError as e:
                # 관측 창이 모자란 기준시점 하나 때문에 전체 실행을 죽이지 않는다.
                # 대신 **조용히 포함시키지도 않는다** — 그게 배율 비교를 어긋나게 한다.
                print(f"\n{'=' * 74}\nT={T} 건너뜀 — {e}")
                continue
        label = {e.corp_code for e in events if is_distress(e.event_type)}
        feats = {c: features(acc_now[c], acc_prev.get(c, {}), cash_now.get(c, {}))
                 for c in acc_now if acc_now[c].get("자산총계")}
        assets = {c: float(acc_now[c]["자산총계"]) for c in feats}
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
            worst = max(rows[1:], key=lambda x: x[1])
            sup = sum(1 for x in rows[1:] if x[2] is Verdict.SUPPORTED)
            ok = worst[2] is Verdict.SUPPORTED
            verdicts[name].append("채택" if ok else "탈락")
            print(f"  {name:16s} {len(hit):>6,} {events_in / len(hit) * 100:6.2f}% "
                  f"×{plain:7.2f} ×{worst[0]:6.2f} {worst[1]:8.4f}  "
                  f"{'채택' if ok else '탈락'} ({sup}/7)")

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
