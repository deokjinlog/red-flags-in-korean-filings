"""수집 대상 명부 — 상장사 전체.

왜 필요한가:
  지금 그래프는 대기업 44곳을 씨앗으로 경계를 한 번 닫아 1,490개사다. 씨앗이 대기업에
  치우쳐 있어 중소형주가 통째로 빠진다. "이 종목 사도 되나" 에 답하려면 **사용자가
  물어볼 종목이 그래프에 있어야** 한다.

  corpCode 는 110,838건이지만 대부분 비상장이라 정기보고서가 없다. 상장사(stock_code
  보유)만 추리면 실제로 조회 가능한 대상이 나온다.

사용:
    uv run python scripts/build_universe.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from dartweave.config import Settings
from dartweave.dart.client import DartClient
from dartweave.dart.corpcode import parse_corpcode_zip

OUT = Path("data/universe_listed.json")


def main() -> int:
    s = Settings.from_env()
    if not s.dart_api_key:
        print("DART_API_KEY 가 없습니다.", file=sys.stderr)
        return 2
    c = DartClient(api_key=s.dart_api_key)
    try:
        rows = parse_corpcode_zip(c.get_bytes("corpCode.xml", {}), listed_only=True)
    finally:
        c.close()
    table = {r.corp_code: r.corp_name for r in rows if r.corp_code and r.corp_name}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(table, ensure_ascii=False), encoding="utf-8")
    print(f"상장사 {len(table):,}개사 → {OUT}")
    print("예:", ", ".join(list(table.values())[:8]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
