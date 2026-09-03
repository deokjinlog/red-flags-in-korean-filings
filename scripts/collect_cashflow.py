"""현금흐름·이자비용 수집 — 주요계정 API 에 없는 것들.

왜 별도 API 인가:
  `fnlttSinglAcnt`(주요계정)는 자산·부채·자본·매출·영업이익·순이익까지만 준다.
  **영업활동현금흐름도 이자비용도 없다.** 그래서 이자보상배율을 못 만들었다.
  전체 재무제표 API(`fnlttSinglAcntAll`)는 계정 257개를 주지만 `fs_div` 가 필수라
  연결(CFS)로 먼저 받고 없으면 개별(OFS)로 다시 받아야 한다.

계정을 이름이 아니라 `account_id` 로 잡는 이유:
  같은 항목을 제출사마다 다르게 쓴다 — "영업활동으로 인한 현금흐름" / "영업활동
  현금흐름" / "영업활동으로부터의 현금흐름". IFRS 표준 id 는 같다.
  주요계정 수집에서 `당기순이익` 으로 찾다가 실제 계정명이 `당기순이익(손실)` 이라
  0건이 나온 사고가 있었다. 같은 실수를 두 번 하지 않는다.

이자비용은 우선순위를 둔다:
  1. `이자의 지급`(현금흐름표) — 실제로 나간 현금이라 가장 곧다
  2. `이자비용`(현금흐름 조정) — 발생주의
  3. `금융원가`(포괄손익) — 이자 외 항목이 섞여 있어 마지막

사용:
    uv run python scripts/collect_cashflow.py --year 2023 --limit 4000
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

OUT = Path("data/cashflow_by_year.json")
TERMS = {"thstrm_amount": 0, "frmtrm_amount": -1, "bfefrmtrm_amount": -2}

# 우리 이름 → IFRS account_id 후보 (앞에 있는 것이 우선)
WANTED: dict[str, tuple[str, ...]] = {
    "영업활동현금흐름": ("ifrs-full_CashFlowsFromUsedInOperatingActivities",
                  "ifrs_CashFlowsFromUsedInOperatingActivities"),
    "이자의지급": ("ifrs-full_InterestPaidClassifiedAsFinancingActivities",
              "ifrs-full_InterestPaidClassifiedAsOperatingActivities",
              "ifrs-full_InterestPaid"),
    "이자비용": ("dart_AdjustmentsForInterestExpenses",
             "ifrs-full_AdjustmentsForInterestExpense"),
    "금융원가": ("ifrs-full_FinanceCosts",),
    # 재무CF 로 연명하는가 — 영업에서 현금이 나가는데 차입·증자로 버티면
    # "조달이 끊기면 죽는 회사" 다.
    "재무활동현금흐름": ("ifrs-full_CashFlowsFromUsedInFinancingActivities",
                  "ifrs_CashFlowsFromUsedInFinancingActivities"),
    "투자활동현금흐름": ("ifrs-full_CashFlowsFromUsedInInvestingActivities",),
    # 매출은 느는데 현금이 안 들어오는가 — 회전율 악화가 여기서 나온다.
    "매출채권": ("ifrs-full_CurrentTradeReceivables",
             "dart_ShortTermTradeReceivable",
             "ifrs-full_TradeAndOtherCurrentReceivables"),
    "재고자산": ("ifrs-full_Inventories",),
    "현금및현금성자산": ("ifrs-full_CashAndCashEquivalents",
                 "dart_CashAndCashEquivalentsAtEndOfPeriod"),
}


def pick(rows: list[dict], year: int) -> dict[str, dict[str, float]]:
    """연도 → 계정 → 금액. 같은 계정이 여러 번 나오면 **먼저 나온 것**을 쓴다."""
    out: dict[str, dict[str, float]] = {}
    for label, ids in WANTED.items():
        for want in ids:
            hits = [r for r in rows if str(r.get("account_id", "")).strip() == want]
            if not hits:
                continue
            for key, offset in TERMS.items():
                raw = re.sub(r"[^\d-]", "", str(hits[0].get(key, "")))
                if raw and raw != "-":
                    out.setdefault(str(year + offset), {})[label] = float(raw)
            break
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--year", default="2023")
    p.add_argument("--limit", type=int, default=4000)
    p.add_argument("--min-interval", type=float, default=0.25,
                   help="요청 간격(초). 0 으로 두면 DART 가 연결을 끊는다 — 겪었다.")
    p.add_argument("--universe", default="data/universe_tested.json")
    args = p.parse_args(argv)

    s = Settings.from_env()
    if not s.dart_api_key:
        print("DART_API_KEY 가 없습니다.", file=sys.stderr)
        return 2

    codes = list(json.loads(Path(args.universe).read_text(encoding="utf-8")))
    store: dict[str, dict[str, dict[str, float]]] = (
        json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    )
    # 이어받기는 이 호출의 마진(전전기) 기준 — 당기로 보면 다른 연도 요청이 통째로 건너뛴다.
    # 이어받기는 **세 항이 다 있는가**로 판단한다. 한 항만 보면 방향에 따라 틀린다 —
    # 전전기로 보면 최신 연도로 갈 때 건너뛰고, 당기로 보면 뒤로 채울 때 건너뛴다.
    # 실측으로 둘 다 겪었다(2021년 요청 통째로 스킵 · 2024년이 136사만 수집).
    years3 = [str(int(args.year) + k) for k in (0, -1, -2)]
    have = {c for c in codes if all(c in store.get(y, {}) for y in years3)}
    todo = [c for c in codes if c not in have][: args.limit]
    if not todo:
        print(f"{args.year}년은 이어받을 게 없습니다 — {len(have):,}/{len(codes):,}")
        return 0

    client = DartClient(api_key=s.dart_api_key, min_interval=args.min_interval)
    got = 0
    try:
        for i, code in enumerate(todo, 1):
            terms: dict[str, dict[str, float]] = {}
            for fs in ("CFS", "OFS"):
                r = client.get_json("fnlttSinglAcntAll.json", {
                    "corp_code": code, "bsns_year": args.year,
                    "reprt_code": "11011", "fs_div": fs})
                if classify(str(r.get("status", ""))) is not Action.OK:
                    continue
                terms = pick(r.get("list") or [], int(args.year))
                if terms:
                    break
            got += bool(terms)
            for y, accounts in terms.items():
                store.setdefault(y, {})[code] = accounts
            # 못 받은 회사도 자리를 만들어야 이어받기가 다시 시도하지 않는다.
            store.setdefault(str(int(args.year) - 2), {}).setdefault(code, {})
            if i % 200 == 0:
                OUT.write_text(json.dumps(store, ensure_ascii=False), encoding="utf-8")
                print(f"  {i}/{len(todo)} · 확보 {got}", flush=True)
    finally:
        client.close()
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(store, ensure_ascii=False), encoding="utf-8")

    print(f"\n{len(todo):,}개사 조회 · 계정 확보 {got:,}사")
    for y in sorted(store):
        n = sum(1 for a in store[y].values() if a.get("영업활동현금흐름") is not None)
        m = sum(1 for a in store[y].values()
                if any(a.get(k) for k in ("이자의지급", "이자비용", "금융원가")))
        print(f"   {y}년 영업활동현금흐름 {n:,}사 · 이자 관련 {m:,}사")
    print(f"→ {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
