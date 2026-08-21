"""관측 창 길이를 흔든다 — 730일도 우리가 고른 값이다.

왜:
  이 저장소는 군집 해상도(0.5~2.0)를 흔들어 층1 결론을 반려했고, 규모·업종 통제
  정밀도를 흔들어 고립 신호를 반려했다. 그런데 **"T 이후 730일 안의 부실"** 의
  730 은 흔들어본 적이 없다. 같은 규율을 여기에도 대야 앞뒤가 맞는다.

무엇이 흔들리면 문제인가:
  창을 늘리면 사건이 늘어 검정력이 오르는 건 **당연하다** — 그건 파라미터 의존이
  아니라 표본 크기다. 문제가 되는 건 **방향이나 채택 여부가 뒤집히는 것**이다.

절단에 주의:
  창이 길어지면 최근 기준시점이 수집 끝을 넘는다. `events_after` 가 막아주고,
  여기서는 그 시점을 빼고 센다 — **빼놓고 세는 것과 조용히 넣고 세는 것은 다르다.**

사용:
    uv run python scripts/sweep_window.py
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
from test_financial_signals import SIGNALS_ORDER, cells_for, features


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--db", default="sqlite:///data/timeseries.db")
    p.add_argument("--as-of", default="20210630,20220630,20230630,20240630")
    p.add_argument("--windows", default="365,730,1095")
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
    windows = [int(w) for w in args.windows.split(",") if w.strip()]
    dates = [x.strip() for x in args.as_of.split(",") if x.strip()]

    tally: dict[tuple[str, int], list[str]] = defaultdict(list)
    for W in windows:
        for T in dates:
            year = str(int(T[:4]) - 1)
            acc, prev = fin.get(year, {}), fin.get(str(int(year) - 1), {})
            cf = cash.get(year, {})
            try:
                with Session(engine) as s:
                    events = events_after(s, T, within_days=W)
            except CensoredWindowError:
                for name in SIGNALS_ORDER:
                    tally[(name, W)].append("—")     # 절단은 빼고 센다
                continue
            label = {e.corp_code for e in events if is_distress(e.event_type)}
            feats = {c: features(acc[c], prev.get(c, {}), cf.get(c, {}))
                     for c in acc if acc[c].get("자산총계")}
            assets = {c: float(acc[c]["자산총계"]) for c in feats}
            pool = sorted(c for c in feats if c in industry)
            for name in SIGNALS_ORDER:
                hit = [c for c in pool if feats[c].get(name)]
                if len(hit) < 30:
                    tally[(name, W)].append("·")
                    continue
                verdicts = []
                for n_strata, digits in ((1, 0), (2, 1), (3, 1), (3, 2), (4, 2)):
                    st = cells_for(pool, assets, industry, label,
                                   lambda c, n=name: bool(feats[c].get(n)),
                                   n_strata, digits)
                    r = stratified_permutation_test(st, runs=args.runs)
                    if r.verdict is Verdict.TOO_FEW:
                        verdicts = None
                        break
                    verdicts.append((mantel_haenszel_ratio(st), r.p_value, r.verdict))
                if verdicts is None:
                    tally[(name, W)].append("?")     # 표본 미달 — 판정 안 함
                    continue
                worst = max(verdicts[1:], key=lambda x: x[1])
                tally[(name, W)].append(
                    f"{'O' if worst[2] is Verdict.SUPPORTED else 'X'}{worst[0]:.1f}")

    print(f"\n  O=채택 X=탈락 ?=표본 미달 ·=해당 기업 부족 —=창이 절단됨"
          f"\n  칸 안의 숫자는 가장 보수적인 통제 설정의 배율\n")
    print(f"  {'신호':14s} " + "  ".join(f"{f'창 {W}일':^{len(dates) * 7}}" for W in windows))
    print(f"  {'':14s} " + "  ".join(" ".join(f"{d[2:4]}{d[4:6]}".rjust(6) for d in dates)
                                     for _ in windows))
    for name in SIGNALS_ORDER:
        row = "  ".join(" ".join(v.rjust(6) for v in tally[(name, W)]) for W in windows)
        print(f"  {name:14s} {row}")
    print("\n  창을 늘리면 사건이 늘어 검정력이 오르는 건 당연하다 — 파라미터 의존이 아니라"
          "\n  표본 크기다. 문제는 **방향이나 채택 여부가 뒤집히는 것**이고, 그건 따로 본다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
