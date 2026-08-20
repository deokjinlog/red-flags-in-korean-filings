"""대규모기업집단 소속 여부를 신호로 검정한다.

왜 이게 검정 가능한 신호인가:
  집단명은 DART 에 없다(list API 에도 `flr_nm` 에도 없음 — 실측 확인). 하지만
  **대규모기업집단현황공시를 제출한다는 것 자체가 소속이라는 뜻**이다. 그건 확실하다.

  그리고 소속률이 순환출자(1.7%)보다 훨씬 높아 표본 문제가 없다.

라벨은 감사의견을 쓴다 — 주요사항보고 기반 라벨은 공시량 편향이 있고, 그 편향이
신호 검정 2호를 통째로 만들어냈다. 감사의견은 모든 상장사가 매년 하나씩 받는다.

사용:
    uv run python scripts/test_conglomerate_signal.py
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from dartweave.screen.audit import has_going_concern, normalize_opinion
from dartweave.signal.test import permutation_test


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--members", default="data/conglomerate_members.json")
    p.add_argument("--audit", default="data/audit_opinions.json")
    p.add_argument("--runs", type=int, default=4000)
    args = p.parse_args(argv)

    mp = Path(args.members)
    if not mp.exists():
        print("소속 명단이 없습니다. `scripts/collect_conglomerate.py` 를 먼저 돌리세요.")
        return 2
    members = set(json.loads(mp.read_text(encoding="utf-8"))["members"])
    audit = json.loads(Path(args.audit).read_text(encoding="utf-8"))

    if len(members) < 500:
        print(f"⚠️ 소속 {len(members)}사는 전수가 아닙니다 — 부분 목록으로 검정하면 "
              "나머지가 전부 '미소속' 으로 잘못 들어갑니다. 수집을 마저 하세요.")
        return 3

    adverse = {c for c, rows in audit.items()
               if any(normalize_opinion(r["opinion"]).is_adverse for r in rows)}
    gc = {c for c, rows in audit.items()
          if any(has_going_concern(r["emphasis"]) for r in rows)}
    label = adverse | gc

    pool = sorted(audit)                       # 감사의견을 확보한 상장사만
    inside = [c in label for c in pool if c in members]
    outside = [c in label for c in pool if c not in members]

    print(f"\n대상 {len(pool):,}사 · 대기업집단 소속 {len(inside):,}사 "
          f"· 감사의견 문제 {len(label & set(pool)):,}사\n")

    # 소속이 '위험' 인지 보려면 소속을 신호군에 둔다.
    r = permutation_test(inside, outside, runs=args.runs)
    print(f"  소속이 위험한가   {r.verdict.value:15s} {r.explain()}")
    # 반대 방향도 본다 — 단측 검정이라 한 번 더 돌려야 안다.
    r2 = permutation_test(outside, inside, runs=args.runs)
    print(f"  미소속이 위험한가 {r2.verdict.value:15s} {r2.explain()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
