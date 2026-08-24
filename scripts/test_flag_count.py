"""몇 개나 걸렸는가 — 체크리스트가 실제로 하는 일을 검정한다.

왜 이걸 안 재면 안 되나:
  우리는 신호를 **하나씩** 검정해왔다. 그런데 사람이 점검표를 쓸 때는 그렇게 안 한다 —
  쭉 훑고 **몇 개나 걸렸는지**를 본다. "세 개 이상 걸리면 멈춘다" 같은 규칙이
  실제 사용법이고, 그게 유효한지는 따로 물어야 한다.

  개수가 늘수록 부실률이 단조로 오르지 않으면 "몇 개 이상" 규칙은 근거가 없다.
  반대로 오른다면 **몇 개부터 멈춰야 하는지**가 데이터로 나온다.

무엇을 세나:
  4개 기준시점 전부에서 채택된 7종만 센다. 미검정·반려 신호를 섞으면 개수가
  뜻을 잃는다. **모르는 신호는 0 으로 세지 않는다** — 재무를 못 받은 회사가
  자동으로 '0개 걸림' 이 되면 안전해 보인다. 7종을 다 아는 회사만 대상으로 한다.

  신호끼리 겹친다(영업손실이면 이자보상배율도 대개 걸린다). 그래서 개수는 독립
  사건의 합이 아니고, 여기서는 그걸 교정하지 않는다 — **사람이 점검표를 쓰는
  방식 그대로** 재는 게 목적이다.

사용:
    uv run python scripts/test_flag_count.py
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
from test_financial_signals import GRID, build_features

ADOPTED = ("결손금", "당기순손실", "영업손실", "영업현금흐름 음수",
           "이자보상배율 1 미만", "최근 3년 CB·BW 발행", "최근 3년 CB·BW 2회 이상")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--db", default="sqlite:///data/timeseries.db")
    p.add_argument("--as-of", default="20210630,20220630,20230630,20240630")
    p.add_argument("--within-days", type=int, default=730)
    p.add_argument("--runs", type=int, default=4000)
    args = p.parse_args(argv)

    engine = create_engine(args.db)
    industry = {k: str(v) for k, v in
                json.loads(Path("data/industry.json").read_text(encoding="utf-8")).items()
                if v}

    for T in [x.strip() for x in args.as_of.split(",") if x.strip()]:
        try:
            with Session(engine) as s:
                events = events_after(s, T, within_days=args.within_days)
        except CensoredWindowError as e:
            print(f"\nT={T} 건너뜀 — {e}")
            continue
        label = {e.corp_code for e in events if is_distress(e.event_type)}
        feats, assets = build_features(T)

        # 7종을 다 아는 회사만. 모르는 걸 0 으로 세면 안전해 보인다.
        pool = [c for c in feats
                if c in industry and c in assets
                and all(feats[c].get(k) is not None for k in ADOPTED)]
        count = {c: sum(bool(feats[c][k]) for k in ADOPTED) for c in pool}

        print(f"\n{'=' * 70}\nT={T} · 7종을 다 아는 회사 {len(pool):,}사 · "
              f"이후 {args.within_days}일 부실 {len(label & set(pool))}사")
        print(f"  {'걸린 개수':>8s} {'회사':>7s} {'부실':>5s} {'부실률':>7s}")
        buckets = defaultdict(list)
        for c in pool:
            buckets[min(count[c], 5)].append(c)
        for k in sorted(buckets):
            g = buckets[k]
            hit = sum(1 for c in g if c in label)
            tag = f"{k}개" if k < 5 else "5개 이상"
            print(f"  {tag:>8s} {len(g):7,} {hit:5d} {hit / len(g) * 100:6.2f}%")

        print(f"\n  {'기준':>10s} {'해당':>6s} {'배율':>7s} {'p':>8s}   판정")
        for cut in (1, 2, 3, 4):
            hit = [c for c in pool if count[c] >= cut]
            if len(hit) < 30:
                continue
            rows = []
            for n_strata, digits in GRID:
                st = _cells(pool, assets, industry, label,
                            lambda c, k=cut: count[c] >= k, n_strata, digits)
                r = stratified_permutation_test(st, runs=args.runs)
                if r.verdict is Verdict.TOO_FEW:
                    rows = None
                    break
                rows.append((mantel_haenszel_ratio(st), r.p_value, r.verdict))
            if not rows:
                print(f"  {cut}개 이상 {len(hit):6,}   표본 미달")
                continue
            worst = max(rows[1:], key=lambda x: x[1])
            print(f"  {f'{cut}개 이상':>10s} {len(hit):6,} ×{worst[0]:6.2f} "
                  f"{worst[1]:8.4f}   "
                  f"{'채택' if worst[2] is Verdict.SUPPORTED else '탈락'}")
    return 0


def _cells(pool, assets, industry, label, is_signal, n_strata, digits):
    ordered = sorted(pool, key=lambda c: assets[c])
    size = max(1, len(ordered) // n_strata)
    buckets = defaultdict(list)
    for i in range(n_strata):
        chunk = ordered[i * size:] if i == n_strata - 1 else ordered[i * size:(i + 1) * size]
        for c in chunk:
            buckets[(i, industry[c][:digits] if digits else "")].append(c)
    return [([c in label for c in g if is_signal(c)],
             [c in label for c in g if not is_signal(c)])
            for g in buckets.values()]


if __name__ == "__main__":
    raise SystemExit(main())
