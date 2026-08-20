"""업종 수집 — 마지막으로 남은 교란.

왜:
  고립군에 특정 업종이 몰려 있으면(예: 바이오·게임처럼 대기업집단 밖에서 태어나고
  감사의견 문제도 잦은 업종) 그 업종을 신호로 착각한 것이 된다. 규모를 통제했듯
  업종도 통제해야 한다.

  업종은 DART 기업개황(company.json)의 표준산업분류코드로 나온다 — 외부 포털이
  필요 없다. 5자리 중 앞 2자리(중분류)를 쓴다. 5자리를 그대로 쓰면 층이 수백 개로
  쪼개져 층마다 표본이 한 자릿수가 된다.

사용:
    uv run python scripts/collect_industry.py --limit 4000
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from dartweave.config import Settings
from dartweave.dart.client import DartClient
from dartweave.dart.company import parse_company
from dartweave.dart.status import Action, classify

OUT = Path("data/industry.json")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=4000)
    p.add_argument("--universe", default="data/universe_tested.json")
    args = p.parse_args(argv)

    s = Settings.from_env()
    if not s.dart_api_key:
        print("DART_API_KEY 가 없습니다.", file=sys.stderr)
        return 2

    codes = list(json.loads(Path(args.universe).read_text(encoding="utf-8")))
    done: dict[str, str | None] = (
        json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    )
    todo = [c for c in codes if c not in done][: args.limit]
    if not todo:
        got = sum(1 for v in done.values() if v)
        print(f"이어받을 게 없습니다 — {len(done):,}/{len(codes):,} · 업종 확보 {got:,}")
        return 0

    client = DartClient(api_key=s.dart_api_key)
    try:
        for i, code in enumerate(todo, 1):
            r = client.get_json("company.json", {"corp_code": code})
            done[code] = (parse_company(code, r).induty_code
                          if classify(str(r.get("status", ""))) is Action.OK else None)
            if i % 200 == 0:
                OUT.write_text(json.dumps(done, ensure_ascii=False), encoding="utf-8")
                print(f"  {i}/{len(todo)}", flush=True)
    finally:
        client.close()
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(done, ensure_ascii=False), encoding="utf-8")

    major = Counter(v[:2] for v in done.values() if v)
    print(f"\n{len(done):,}개사 조회 · 업종 확보 {sum(major.values()):,}사 "
          f"· 중분류 {len(major)}종")
    for k, n in major.most_common(6):
        print(f"   {k} {n:>5,}사")
    print(f"→ {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
