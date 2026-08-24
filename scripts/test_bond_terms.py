"""조항이 횟수 위에 뭘 더 얹는가.

이미 아는 것:
  "최근 3년 CB·BW 2회 이상" 은 네 기준시점 전부에서 채택됐다(×2.52~6.69).
  검정한 24종 중 가장 강하다. **그런데 그건 개수만 본다** — 오버행 26%짜리와
  7%짜리를 같은 "1회" 로 센다.

물어야 할 것:
  조항이 **횟수를 알고 나서도** 뭘 더 얹는가. 층에 발행 횟수를 넣고 조항을
  검정하면 답이 나온다 — 구조를 재무 위에서 검정했던 것과 같은 방식이다.

  같은 규모·같은 업종·**같은 발행 횟수**끼리만 비교한다. 그러고도 오버행 큰 쪽이
  더 위험하면 조항이 뭔가 얹는 것이고, 아니면 횟수만 세면 된다.

조항 신호:
  오버행 상위      전환가능주식수 ÷ 발행주식총수 (제출사 신고값 `STK_RT`)
  리픽싱 하한 깊음   하한 ÷ 전환가. 낮을수록 희석 폭탄
  풋옵션 있음       투자자가 조기상환을 청구할 수 있다 = 유동성 위기 방아쇠
  콜옵션 있음       최대주주·제3자가 되사올 수 있다 = 잠재 오버행 + 이해상충

  "상위" 는 그 기준시점 표본 안에서 자른다. 절대 임계를 쓰면 시장 상황이 다른
  연도끼리 같은 뜻이 아니게 된다.

사용:
    uv run python scripts/test_bond_terms.py
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

# 층이 세 겹(자산 × 업종 × 발행횟수)이라 셀이 빨리 마른다. 거친 설정부터 두고,
# **판정 가능한 것만** 센다 — 하나가 표본 미달이라고 전체를 버리면 아무것도 못 본다.
GRID = [(1, 0), (2, 0), (2, 1), (3, 1)]


def per_company(bonds: dict, terms: dict, window: set[str]) -> dict[str, dict]:
    """T 이전 3년 발행을 회사별로 모은다. 조항을 못 받은 발행은 **세지 않는다.**"""
    out: dict[str, dict] = {}
    for rcept, meta in bonds.items():
        code, date = meta.get("corp_code"), meta.get("date", "")
        if not code or date[:4] not in window:
            continue
        slot = out.setdefault(code, {"count": 0, "with_terms": 0, "overhang": [],
                                     "refix": [], "put": False, "call": False})
        slot["count"] += 1
        t = terms.get(rcept)
        if not t:
            continue
        slot["with_terms"] += 1
        if t.get("overhang_pct") is not None:
            slot["overhang"].append(float(t["overhang_pct"]))
        floor, price = t.get("refix_floor"), t.get("exercise_price")
        if floor and price:
            slot["refix"].append(float(floor) / float(price) * 100.0)
        slot["put"] = slot["put"] or bool(t.get("has_put"))
        slot["call"] = slot["call"] or bool(t.get("has_call"))
    return out


def signals(rec: dict, oh_cut: float, rf_cut: float) -> dict[str, bool | None]:
    """조항을 못 받았으면 None — 못 받은 걸 '조항 없음' 으로 세지 않는다."""
    if rec["with_terms"] == 0:
        return {k: None for k in
                ("오버행 상위", "리픽싱 하한 깊음", "풋옵션 있음", "콜옵션 있음")}
    return {
        "오버행 상위": (max(rec["overhang"]) >= oh_cut if rec["overhang"] else None),
        "리픽싱 하한 깊음": (min(rec["refix"]) <= rf_cut if rec["refix"] else None),
        "풋옵션 있음": rec["put"],
        "콜옵션 있음": rec["call"],
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--as-of", default="20230630,20240630")
    p.add_argument("--within-days", type=int, default=730)
    p.add_argument("--runs", type=int, default=4000)
    args = p.parse_args(argv)

    read = lambda f: json.loads(Path(f).read_text(encoding="utf-8"))  # noqa: E731
    bonds, terms = read("data/bond_filings.json"), read("data/bond_terms.json")
    industry = {k: str(v) for k, v in read("data/industry.json").items() if v}
    by_year = {y: {k: float(v) for k, v in d.items()}
               for y, d in read("data/assets_by_year.json").items()}
    engine = create_engine("sqlite:///data/timeseries.db")

    for T in [x.strip() for x in args.as_of.split(",") if x.strip()]:
        try:
            with Session(engine) as s:
                events = events_after(s, T, within_days=args.within_days)
        except CensoredWindowError as e:
            print(f"\nT={T} 건너뜀 — {e}")
            continue
        label = {e.corp_code for e in events if is_distress(e.event_type)}
        assets = by_year.get(str(int(T[:4]) - 1), {})
        window = {str(int(T[:4]) - k) for k in (1, 2, 3)}
        recs = per_company(bonds, terms, window)
        pool = [c for c in recs if c in assets and c in industry]

        oh = sorted(v for c in pool for v in recs[c]["overhang"])
        rf = sorted(v for c in pool for v in recs[c]["refix"])
        if len(oh) < 40:
            print(f"\nT={T} · 조항 확보가 {len(oh)}건뿐이라 판정 보류")
            continue
        oh_cut = oh[int(len(oh) * 0.75)]
        rf_cut = rf[int(len(rf) * 0.25)] if len(rf) >= 40 else 0.0
        feats = {c: signals(recs[c], oh_cut, rf_cut) for c in pool}
        covered = sum(1 for c in pool if recs[c]["with_terms"])

        print(f"\n{'=' * 72}\nT={T} · 3년 안에 발행한 회사 {len(pool):,}사 "
              f"(조항 확보 {covered:,}사) · 이후 부실 {len(label & set(pool))}사")
        print(f"  오버행 상위 기준 {oh_cut:.1f}% · 리픽싱 하한 기준 {rf_cut:.0f}%")
        print(f"\n  {'조항':16s} {'해당':>6s} {'부실률':>7s} {'배율':>7s} {'p':>8s}   판정")
        for name in ("오버행 상위", "리픽싱 하한 깊음", "풋옵션 있음", "콜옵션 있음"):
            hit = [c for c in pool if feats[c][name]]
            if len(hit) < 30:
                print(f"  {name:16s} {len(hit):6,}   해당 기업이 적어 보류")
                continue
            rows = []
            for n_strata, digits in GRID:
                cells = _cells(pool, assets, industry, recs, label, feats, name,
                               n_strata, digits)
                r = stratified_permutation_test(cells, runs=args.runs)
                if r.verdict is Verdict.TOO_FEW:
                    continue                       # 이 설정만 못 본다
                rows.append((mantel_haenszel_ratio(cells), r.p_value, r.verdict))
            events_in = sum(1 for c in hit if c in label)
            rate = events_in / len(hit) * 100
            if len(rows) < 2:
                print(f"  {name:16s} {len(hit):6,} {rate:6.2f}%"
                      f"   통제 설정을 하나도 못 봄 (부실 {events_in}건)")
                continue
            worst = max(rows[1:], key=lambda x: x[1])
            print(f"  {name:16s} {len(hit):6,} {rate:6.2f}% "
                  f"×{worst[0]:6.2f} {worst[1]:8.4f}   "
                  f"{'채택' if worst[2] is Verdict.SUPPORTED else '탈락'}"
                  f" ({len(rows)}/{len(GRID)} 설정 판정)")
    print("\n※ 층에 **발행 횟수**가 들어 있다. 같은 규모·같은 업종·같은 횟수끼리만"
          "\n   비교하므로, 여기서 남는 건 횟수로는 설명되지 않는 부분이다.")
    return 0


def _cells(pool, assets, industry, recs, label, feats, name, n_strata, digits):
    """자산 층 × 업종 × **발행 횟수** 교차. 횟수를 층에 넣는 게 이 검정의 핵심이다."""
    codes = [c for c in pool if feats[c][name] is not None]
    codes.sort(key=lambda c: assets[c])
    size = max(1, len(codes) // n_strata)
    buckets = defaultdict(list)
    for i in range(n_strata):
        chunk = codes[i * size:] if i == n_strata - 1 else codes[i * size:(i + 1) * size]
        for c in chunk:
            buckets[(i, industry[c][:digits] if digits else "",
                     min(recs[c]["count"], 3))].append(c)
    return [([c in label for c in g if feats[c][name]],
             [c in label for c in g if not feats[c][name]])
            for g in buckets.values()]


if __name__ == "__main__":
    raise SystemExit(main())
