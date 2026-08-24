"""전환사채·신주인수권부사채 발행결정 수집 — 횟수가 아니라 조항까지.

두 단계로 나눈다:
  1. 목록 — 주요사항보고(pblntf_ty=B)를 분기로 훑어 CB/BW 발행결정만 고른다.
     여기까지가 "몇 번 했는가" 다. 값이 싸다(호출 한 번에 100건).
  2. 조항 — 우리 검정 대상 기업 것만 원문을 열어 오버행·리픽싱 하한·풋/콜을 읽는다.
     원문은 한 건 33KB 로 작아서 정기보고서(7MB)보다 훨씬 가볍다.

  전 종목 원문을 다 여는 건 낭비다. 검정에 못 쓰는 회사(재무·업종을 못 받은 곳)
  것까지 받아봐야 표본에 안 들어간다.

⚠️ corp_code 없는 기간 검색은 3개월 제한이라 분기로 끊는다 — `collect_events` 와 같다.

사용:
    uv run python scripts/collect_bonds.py --years 2019,2020,2021,2022,2023,2024
    uv run python scripts/collect_bonds.py --terms          # 2단계: 조항 읽기
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from dartweave.config import Settings
from dartweave.dart.client import DartClient
from dartweave.dart.status import Action, classify
from dartweave.parse.bond import parse_bond

LIST_OUT = Path("data/bond_filings.json")
TERM_OUT = Path("data/bond_terms.json")
QUARTERS = [("0101", "0331"), ("0401", "0630"), ("0701", "0930"), ("1001", "1231")]
KINDS = ("전환사채권 발행결정", "신주인수권부사채권 발행결정", "교환사채권 발행결정")


def kind_of(report_nm: str) -> str | None:
    for k in KINDS:
        if k.replace(" ", "") in report_nm.replace(" ", ""):
            return k
    return None


def collect_list(client: DartClient, years: list[str], max_pages: int) -> dict:
    store: dict[str, dict] = (
        json.loads(LIST_OUT.read_text(encoding="utf-8")) if LIST_OUT.exists() else {}
    )
    for year in years:
        for bgn, end in QUARTERS:
            for page in range(1, max_pages + 1):
                payload = client.get_json("list.json", {
                    "bgn_de": f"{year}{bgn}", "end_de": f"{year}{end}",
                    "pblntf_ty": "B", "page_count": "100", "page_no": str(page)})
                if classify(str(payload.get("status", ""))) is not Action.OK:
                    break
                items = payload.get("list") or []
                for it in items:
                    kind = kind_of(str(it.get("report_nm", "")))
                    if not kind:
                        continue
                    store[str(it["rcept_no"])] = {
                        "corp_code": it.get("corp_code"),
                        "corp_name": it.get("corp_name"),
                        "date": str(it.get("rcept_dt", "")),
                        "kind": kind,
                    }
                if len(items) < 100:
                    break
            print(f"  {year}{bgn} 누적 {len(store):,}", flush=True)
    LIST_OUT.write_text(json.dumps(store, ensure_ascii=False), encoding="utf-8")
    return store


def collect_terms(client: DartClient, limit: int) -> dict:
    filings = json.loads(LIST_OUT.read_text(encoding="utf-8"))
    universe = set(json.loads(
        Path("data/universe_tested.json").read_text(encoding="utf-8")))
    terms: dict[str, dict] = (
        json.loads(TERM_OUT.read_text(encoding="utf-8")) if TERM_OUT.exists() else {}
    )
    todo = [r for r, v in filings.items()
            if v.get("corp_code") in universe and r not in terms][:limit]
    print(f"조항을 읽을 대상 {len(todo):,}건 (전체 {len(filings):,} 중 검정 대상만)")
    for i, rcept in enumerate(todo, 1):
        try:
            issue = parse_bond(client.get_document(rcept))
        except Exception as exc:                          # noqa: BLE001
            print(f"  {rcept} 실패 — {type(exc).__name__}")
            terms[rcept] = {}
            continue
        terms[rcept] = asdict(issue) if issue else {}
        if i % 100 == 0:
            TERM_OUT.write_text(json.dumps(terms, ensure_ascii=False), encoding="utf-8")
            print(f"  {i}/{len(todo)}", flush=True)
    TERM_OUT.write_text(json.dumps(terms, ensure_ascii=False), encoding="utf-8")
    return terms


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--years", default="2019,2020,2021,2022,2023,2024,2025")
    p.add_argument("--max-pages", type=int, default=40)
    p.add_argument("--terms", action="store_true", help="2단계 — 원문에서 조항 읽기")
    p.add_argument("--limit", type=int, default=4000)
    args = p.parse_args(argv)

    s = Settings.from_env()
    if not s.dart_api_key:
        print("DART_API_KEY 가 없습니다.", file=sys.stderr)
        return 2
    client = DartClient(api_key=s.dart_api_key)
    try:
        if args.terms:
            terms = collect_terms(client, args.limit)
            got = [v for v in terms.values() if v]
            print(f"\n조항 확보 {len(got):,}/{len(terms):,}건")
            if got:
                priv = sum(1 for v in got if v.get("private"))
                put = sum(1 for v in got if v.get("has_put"))
                call = sum(1 for v in got if v.get("has_call"))
                oh = sorted(v["overhang_pct"] for v in got if v.get("overhang_pct"))
                print(f"   사모 {priv:,} · 풋옵션 {put:,} · 콜옵션 {call:,}")
                if oh:
                    print(f"   오버행 중앙값 {oh[len(oh) // 2]:.1f}% · "
                          f"상위 10% {oh[int(len(oh) * 0.9)]:.1f}%")
            print(f"→ {TERM_OUT}")
            return 0

        store = collect_list(client, [y.strip() for y in args.years.split(",")],
                             args.max_pages)
        kinds = Counter(v["kind"] for v in store.values())
        print(f"\n발행결정 {len(store):,}건")
        for k, n in kinds.most_common():
            print(f"   {k:22s} {n:5,}")
        print(f"→ {LIST_OUT}")
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
