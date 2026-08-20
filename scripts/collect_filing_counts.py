"""회사별 총 공시 건수 — 탐지 편향을 가르기 위한 통제 변수.

왜 필요한가:
  신호 검정 2호에서 "지분 관계가 많은 회사가 부실 2배" 가 나왔다. 그런데 관계가 많은
  회사는 **공시를 많이 하는 회사**이기도 하고, 그러면 부실 공시가 잡힐 확률 자체가
  높다. 실제로 위험한 게 아니라 우리 눈에 더 잘 띄는 것일 수 있다.

  총 공시 건수를 맞춰놓고도 효과가 남으면 진짜 신호다. 사라지면 우리가 공시 많이 하는
  회사를 위험하다고 착각한 것이다.

한 회사당 1회 호출로 끝난다 — list.json 이 `total_count` 를 준다. 페이지를 넘길 필요 없다.

사용:
    uv run python scripts/collect_filing_counts.py --years 2022,2023 --limit 12000
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dartweave.config import Settings
from dartweave.dart.client import DartClient
from dartweave.dart.status import Action, classify

OUT = Path("data/filing_counts.json")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--years", default="2022,2023")
    p.add_argument("--limit", type=int, default=12000)
    p.add_argument("--universe", default="data/universe_listed.json")
    args = p.parse_args(argv)

    s = Settings.from_env()
    if not s.dart_api_key:
        print("DART_API_KEY 가 없습니다.", file=sys.stderr)
        return 2

    codes = list(json.loads(Path(args.universe).read_text(encoding="utf-8")))
    done: dict[str, int] = (
        json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    )
    years = [y.strip() for y in args.years.split(",") if y.strip()]
    todo = [c for c in codes if c not in done][: args.limit]
    if not todo:
        print(f"이어받을 게 없습니다 — {len(done):,}/{len(codes):,} 완료")
        return 0

    client = DartClient(api_key=s.dart_api_key)
    try:
        for i, code in enumerate(todo, 1):
            total = 0
            for y in years:
                r = client.get_json("list.json", {
                    "corp_code": code, "bgn_de": f"{y}0101", "end_de": f"{y}1231",
                    "page_count": "1"})
                if classify(str(r.get("status", ""))) is Action.OK:
                    total += int(r.get("total_count", 0))
            done[code] = total
            if i % 100 == 0:
                OUT.write_text(json.dumps(done), encoding="utf-8")
                print(f"  {i}/{len(todo)}", flush=True)
    finally:
        client.close()
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(done), encoding="utf-8")

    vals = sorted(done.values())
    n = len(vals)
    print(f"\n{n:,}개사 · 공시 건수 중위 {vals[n//2]} · "
          f"p90 {vals[int(n*0.9)]} · 최대 {vals[-1]}")
    print(f"→ {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
