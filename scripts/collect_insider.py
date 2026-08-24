"""오너 리스크 수집 — 내부자 매도와 최대주주 변경.

두 가지를 받는다:
  `elestock.json`     임원·주요주주 특정증권등 소유상황보고. **증감 칸이 있다**
                      (`sp_stock_lmp_irds_cnt`) — 실측으로 삼부토건 지배주주가
                      -16,585,879주(-8.01%p). 내부자 매도가 그대로 잡힌다.
  `hyslrChgSttus.json` 최대주주 변경 이력. 변경일자와 사유가 온다.

시점 분리를 어떻게 지키나:
  두 API 다 `bsns_year` 로 받지만 **행마다 접수일(`rcept_dt`)·변경일(`change_on`)이
  붙어 있다.** 그 날짜로 자른다 — 사업연도로만 자르면 그 해 12월 보고가 6월
  기준시점에 딸려 들어온다.

⚠️ 원문(document.xml)이 아니라 JSON 이라 가볍다. 그래도 회사당 2회 × 4,000사면
   8,000 호출이라 간격을 둔다 — 원문 8,878건을 몰아 던졌다가 IP 가 차단된 적이 있다.

사용:
    uv run python scripts/collect_insider.py --year 2023
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

OUT = Path("data/insider.json")


def _int(raw) -> int | None:
    cleaned = re.sub(r"[^\d-]", "", str(raw or ""))
    try:
        return int(cleaned)
    except ValueError:
        return None


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--year", default="2023")
    p.add_argument("--limit", type=int, default=4000)
    p.add_argument("--universe", default="data/universe_tested.json")
    p.add_argument("--min-interval", type=float, default=0.1)
    args = p.parse_args(argv)

    s = Settings.from_env()
    if not s.dart_api_key:
        print("DART_API_KEY 가 없습니다.", file=sys.stderr)
        return 2

    codes = list(json.loads(Path(args.universe).read_text(encoding="utf-8")))
    store: dict[str, dict] = (
        json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    )
    year = store.setdefault(args.year, {})
    todo = [c for c in codes if c not in year][: args.limit]
    if not todo:
        print(f"{args.year}년은 이어받을 게 없습니다 — {len(year):,}/{len(codes):,}")
        return 0

    client = DartClient(api_key=s.dart_api_key, min_interval=args.min_interval)
    try:
        for i, code in enumerate(todo, 1):
            rec: dict = {"insider": [], "owner_change": []}
            r = client.get_json("elestock.json", {
                "corp_code": code, "bsns_year": args.year, "reprt_code": "11011"})
            if classify(str(r.get("status", ""))) is Action.OK:
                for it in (r.get("list") or []):
                    rec["insider"].append({
                        "date": str(it.get("rcept_dt", "")).replace("-", ""),
                        "who": str(it.get("repror", "")),
                        "role": str(it.get("isu_main_shrholdr", "")),
                        "delta": _int(it.get("sp_stock_lmp_irds_cnt")),
                        "delta_rate": str(it.get("sp_stock_lmp_irds_rate", "")),
                    })
            r = client.get_json("hyslrChgSttus.json", {
                "corp_code": code, "bsns_year": args.year, "reprt_code": "11011"})
            if classify(str(r.get("status", ""))) is Action.OK:
                for it in (r.get("list") or []):
                    rec["owner_change"].append({
                        "on": re.sub(r"\D", "", str(it.get("change_on", ""))),
                        "who": str(it.get("mxmm_shrholdr_nm", "")),
                        "cause": str(it.get("change_cause", "")),
                    })
            year[code] = rec
            if i % 200 == 0:
                OUT.write_text(json.dumps(store, ensure_ascii=False), encoding="utf-8")
                print(f"  {i}/{len(todo)}", flush=True)
    finally:
        client.close()
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(store, ensure_ascii=False), encoding="utf-8")

    ins = sum(1 for v in year.values() if v["insider"])
    sells = sum(1 for v in year.values()
                if any((x["delta"] or 0) < 0 for x in v["insider"]))
    chg = sum(1 for v in year.values() if v["owner_change"])
    print(f"\n{args.year}년 {len(year):,}사 · 내부자 보고 있는 회사 {ins:,} "
          f"(그중 매도 {sells:,}) · 최대주주 변경 이력 {chg:,}")
    print(f"→ {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
