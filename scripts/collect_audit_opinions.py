"""감사의견 수집 — 탐지 편향이 없는 라벨.

왜 이 라벨인가:
  주요사항보고 기반 부실 라벨은 **공시를 많이 하는 회사일수록 잡힐 확률이 높다.**
  실제로 그 편향이 신호 검정 2호를 통째로 만들어냈다(×1.90 → 통제하니 ×0.16~0.53).

  감사의견은 다르다. **모든 상장사가 매년 받는다.** 공시를 많이 하든 적게 하든
  의견 하나가 붙는다. 탐지 확률이 회사마다 다르지 않으니 그 편향이 구조적으로 없다.

무엇을 라벨로 쓰나:
  `adt_opinion != 적정`      한정·부적정·의견거절 — 강한 신호
  `emphs_matter` 에 계속기업  감사인이 명시적으로 단 경고 — 부도보다 앞선다

한 번 호출에 3개 연도(당기·전기·전전기)가 온다.

사용:
    uv run python scripts/collect_audit_opinions.py --year 2023 --limit 4000
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

OUT = Path("data/audit_opinions.json")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--year", default="2023", help="조회 사업연도 (당기·전기·전전기가 함께 온다)")
    p.add_argument("--limit", type=int, default=4000)
    p.add_argument("--universe", default="data/universe_listed.json")
    args = p.parse_args(argv)

    s = Settings.from_env()
    if not s.dart_api_key:
        print("DART_API_KEY 가 없습니다.", file=sys.stderr)
        return 2

    codes = list(json.loads(Path(args.universe).read_text(encoding="utf-8")))
    done: dict[str, list] = (
        json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    )
    todo = [c for c in codes if c not in done][: args.limit]
    if not todo:
        print(f"이어받을 게 없습니다 — {len(done):,}/{len(codes):,}")
        return 0

    client = DartClient(api_key=s.dart_api_key)
    try:
        for i, code in enumerate(todo, 1):
            rows = []
            r = client.get_json("accnutAdtorNmNdAdtOpinion.json",
                                {"corp_code": code, "bsns_year": args.year,
                                 "reprt_code": "11011"})
            if classify(str(r.get("status", ""))) is Action.OK:
                for it in (r.get("list") or []):
                    rows.append({
                        "term": re.sub(r"\s+", "", str(it.get("bsns_year", ""))),
                        "opinion": str(it.get("adt_opinion", "")).strip(),
                        "emphasis": str(it.get("emphs_matter", ""))[:200],
                        "stlm_dt": str(it.get("stlm_dt", "")),
                    })
            done[code] = rows
            if i % 200 == 0:
                OUT.write_text(json.dumps(done, ensure_ascii=False), encoding="utf-8")
                print(f"  {i}/{len(todo)}", flush=True)
    finally:
        client.close()
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(done, ensure_ascii=False), encoding="utf-8")

    from collections import Counter
    ops = Counter(r["opinion"] for v in done.values() for r in v)
    going = sum(1 for v in done.values() for r in v if "계속기업" in r["emphasis"])
    print(f"\n{len(done):,}개사 · 의견 {sum(ops.values()):,}건")
    for k, n in ops.most_common(6):
        print(f"   {k or '(공란)':10s} {n:>6,}")
    print(f"   계속기업 불확실성 강조사항 {going:,}건")
    print(f"→ {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
