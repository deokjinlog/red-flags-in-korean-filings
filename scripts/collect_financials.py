"""자산총계 수집 — 부실 여부와 독립인 진짜 규모 변수.

왜 필요한가:
  "고립이 위험하다" 에 대한 가장 그럴듯한 반박은 **"고립 = 작은 회사"** 다.
  대기업집단 소속은 큰 회사고, 작은 회사가 감사의견 문제가 많은 건 당연하다.
  규모를 맞춰놓고도 차이가 남아야 신호다.

왜 공시 건수로는 안 되는가:
  공시 건수는 규모의 대리변수처럼 보이지만 **부실도 같이 잡는다** — 유상증자·소송·
  관리종목 지정이 전부 공시다. 실측에서 공시 최상위 층의 고립군이 18.7% 로 튀었다.
  층화 변수가 결과변수와 얽히면 층화가 통제가 아니라 왜곡이 된다.

자산총계는 다르다. 회사가 부실해진다고 자산 규모 자체가 정의상 달라지지 않는다.

단일회사 주요계정(fnlttSinglAcnt.json)은 한 번 호출에 당기·전기·전전기가 온다.
연결(CFS)이 있으면 연결을, 없으면 개별(OFS)을 쓴다.

사용:
    uv run python scripts/collect_financials.py --year 2023 --limit 4000
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from dartweave.config import Settings
from dartweave.dart.client import DartClient
from dartweave.dart.status import Action, classify

OUT = Path("data/assets.json")               # 당기 자산총계 (평면)
BY_YEAR = Path("data/assets_by_year.json")   # 연도 → 회사 → 자산총계


TERMS = {"thstrm_amount": 0, "frmtrm_amount": -1, "bfefrmtrm_amount": -2}


def pick_assets(rows: list[dict], year: int) -> dict[str, float]:
    """연도별 자산총계. 연결 우선, 없으면 개별.

    한 번 호출에 당기·전기·전전기가 온다. 셋 다 저장해야 **시점 분리**가 된다 —
    2022년 6월 기준으로 예측하면서 2023년 자산으로 층을 나누면 미래를 보는 것이다.
    """
    best: dict[tuple[str, str], float] = {}
    for it in rows:
        if str(it.get("account_nm", "")).replace(" ", "") != "자산총계":
            continue
        fs = str(it.get("fs_div", ""))
        for key, offset in TERMS.items():
            amount = re.sub(r"[^\d-]", "", str(it.get(key, "")))
            if not amount or amount == "-":
                continue
            best[(fs, str(year + offset))] = float(amount)
    out: dict[str, float] = {}
    for (fs, y), v in best.items():
        if fs == "CFS" or y not in out:
            out[y] = v
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--year", default="2023")
    p.add_argument("--limit", type=int, default=4000)
    p.add_argument("--universe", default="data/universe_tested.json",
                   help="검정 대상만 — 전체 상장 이력에는 폐지사가 절반 가까이 섞여 있다")
    args = p.parse_args(argv)

    s = Settings.from_env()
    if not s.dart_api_key:
        print("DART_API_KEY 가 없습니다.", file=sys.stderr)
        return 2

    codes = list(json.loads(Path(args.universe).read_text(encoding="utf-8")))
    done: dict[str, float | None] = (
        json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    )
    by_year: dict[str, dict[str, float]] = (
        json.loads(BY_YEAR.read_text(encoding="utf-8")) if BY_YEAR.exists() else {}
    )
    todo = [c for c in codes if c not in done][: args.limit]
    if not todo:
        got = sum(1 for v in done.values() if v)
        print(f"이어받을 게 없습니다 — {len(done):,}/{len(codes):,} · 자산 확보 {got:,}")
        return 0

    client = DartClient(api_key=s.dart_api_key)
    try:
        for i, code in enumerate(todo, 1):
            r = client.get_json("fnlttSinglAcnt.json",
                                {"corp_code": code, "bsns_year": args.year,
                                 "reprt_code": "11011"})
            terms = (pick_assets(r.get("list") or [], int(args.year))
                     if classify(str(r.get("status", ""))) is Action.OK else {})
            done[code] = terms.get(args.year)
            for y, v in terms.items():
                by_year.setdefault(y, {})[code] = v
            if i % 200 == 0:
                OUT.write_text(json.dumps(done, ensure_ascii=False), encoding="utf-8")
                BY_YEAR.write_text(json.dumps(by_year, ensure_ascii=False), encoding="utf-8")
                print(f"  {i}/{len(todo)}", flush=True)
    finally:
        client.close()
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(done, ensure_ascii=False), encoding="utf-8")
        BY_YEAR.write_text(json.dumps(by_year, ensure_ascii=False), encoding="utf-8")

    vals = sorted(v for v in done.values() if v)
    print(f"\n{len(done):,}개사 조회 · 자산총계 확보 {len(vals):,}사")
    if vals:
        mid = vals[len(vals) // 2]
        print(f"   중앙값 {mid / 1e8:,.0f}억 · 최대 {vals[-1] / 1e8:,.0f}억")
    for y in sorted(by_year):
        print(f"   {y}년 {len(by_year[y]):,}사")
    print(f"→ {OUT} · {BY_YEAR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
