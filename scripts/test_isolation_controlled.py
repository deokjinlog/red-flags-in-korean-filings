"""고립 신호가 '그냥 작은 회사' 의 다른 이름인지 검사한다.

가장 그럴듯한 반박:
  대기업집단 소속은 큰 회사다. 고립은 작은 회사다. 작은 회사가 감사의견 문제가
  많은 건 당연하니, 1.8% → 3.2% → 7.7% 는 **규모를 다르게 부른 것뿐**일 수 있다.

통제 방법 — 층화:
  규모가 비슷한 회사끼리 층을 나누고, **같은 층 안에서만** 고립군과 나머지를 비교한다.
  층 안에서는 규모가 비슷하니, 그러고도 차이가 남으면 규모로는 설명되지 않는 것이다.

  층화 변수는 갈아끼울 수 있다(`--strata`). 무엇으로 층을 나누느냐가 결론을 바꾼다:

  - `filing_counts.json` (공시 건수) — **오염된 대리변수다.** 부실한 회사가 공시를
    많이 낸다(유상증자·소송·관리종목). 규모만 잡는 게 아니라 부실도 같이 잡으므로
    이걸로 층을 나누면 층 안에 부실이 몰린다. 실측: 최상위 층 고립군 18.7%.
  - `assets.json` (자산총계) — 부실 여부와 독립인 진짜 규모. 이게 본 검정이다.

  층별로 따로 내고 방향이 일관되는지를 본다. 층 대부분이 같은 방향이면 견고하다.

사용:
    uv run python scripts/test_isolation_controlled.py --strata data/assets.json
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from dartweave.screen.audit import has_going_concern, normalize_opinion
from dartweave.signal.test import (
    mantel_haenszel_ratio,
    permutation_test,
    stratified_permutation_test,
)

N_STRATA = 4
MIN_CELL = 40


def groups(edges, members, pool):
    """소속 / 미소속·연결 / 미소속·고립 세 갈래로 나눈다."""
    nb = defaultdict(set)
    for a, b, *_ in edges:
        nb[a].add(b)
        nb[b].add(a)
    out = {"소속": [], "연결": [], "고립": []}
    for c in pool:
        if c in members:
            out["소속"].append(c)
        elif nb[c] & members:
            out["연결"].append(c)
        else:
            out["고립"].append(c)
    return out


def rate(codes, label):
    hit = sum(1 for c in codes if c in label)
    return hit, len(codes), (hit / len(codes) * 100 if codes else 0.0)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--graph", default="data/graph_listed.json")
    p.add_argument("--members", default="data/conglomerate_members.json")
    p.add_argument("--audit", default="data/audit_opinions.json")
    p.add_argument("--strata", default="data/assets.json",
                   help="층화 변수 — corp_code → 수치 매핑 JSON")
    p.add_argument("--runs", type=int, default=4000)
    args = p.parse_args(argv)

    for path in (args.graph, args.members, args.audit, args.strata):
        if not Path(path).exists():
            print(f"입력이 없습니다: {path}")
            return 2

    edges = json.loads(Path(args.graph).read_text(encoding="utf-8"))["edges"]
    members = set(json.loads(Path(args.members).read_text(encoding="utf-8"))["members"])
    audit = json.loads(Path(args.audit).read_text(encoding="utf-8"))
    counts: dict[str, float] = {
        k: float(v) for k, v in
        json.loads(Path(args.strata).read_text(encoding="utf-8")).items()
        if v is not None
    }

    label = {c for c, rows in audit.items()
             if any(normalize_opinion(r["opinion"]).is_adverse for r in rows)
             or any(has_going_concern(r["emphasis"]) for r in rows)}

    # 커버리지 편향 — 그래프 밖 회사는 오히려 문제가 적다(2.2% vs 6.6%). 섞으면 흐려진다.
    in_graph = {v for e in edges for v in e[:2]}
    pool = sorted(c for c in audit if c in in_graph and c in counts)
    g = groups(edges, members, pool)

    print(f"\n대상 {len(pool):,}사 (그래프 안 · 층화 변수 확보) · "
          f"감사의견 문제 {len(label & set(pool)):,}사")
    print("\n[통제 전]")
    for k in ("소속", "연결", "고립"):
        h, n, r = rate(g[k], label)
        print(f"  {k:4s} {r:5.1f}%  ({h}/{n})")

    pool.sort(key=lambda c: counts[c])
    size = max(1, len(pool) // N_STRATA)
    print(f"\n[{Path(args.strata).stem} 으로 {N_STRATA}층 층화 — "
          "층 안에서는 규모가 비슷하다]")
    kept = mono = 0
    cells_by_stratum: list[tuple[list[bool], list[bool]]] = []
    for i in range(N_STRATA):
        chunk = pool[i * size:] if i == N_STRATA - 1 else pool[i * size:(i + 1) * size]
        sub = groups(edges, members, chunk)
        lo, hi = counts[chunk[0]], counts[chunk[-1]]
        unit = f"{lo:,.0f}~{hi:,.0f}"
        cells = {k: rate(sub[k], label) for k in ("소속", "연결", "고립")}
        line = "  ".join(f"{k} {c[2]:4.1f}% ({c[0]}/{c[1]})" for k, c in cells.items())
        print(f"\n  층{i + 1} {unit} · {len(chunk)}사")
        print(f"    {line}")
        iso = [c in label for c in sub["고립"]]
        rest = [c in label for c in sub["소속"] + sub["연결"]]
        if min(len(iso), len(rest)) < MIN_CELL:
            print(f"    → 한쪽이 {MIN_CELL}사 미만이라 판정 보류")
            continue
        kept += 1
        cells_by_stratum.append((iso, rest))
        r_iso = sum(iso) / len(iso) * 100
        r_rest = sum(rest) / len(rest) * 100
        if r_iso > r_rest:
            mono += 1
            print(f"    → 고립 {r_iso:.1f}% > 나머지 {r_rest:.1f}% (방향 유지)")
        else:
            print(f"    → 고립 {r_iso:.1f}% ≤ 나머지 {r_rest:.1f}% (방향 깨짐)")
        r = permutation_test(iso, rest, runs=args.runs)
        print(f"    고립이 위험한가  {r.verdict.value:13s} {r.explain()}")

    print(f"\n판정 가능한 층 {kept}/{N_STRATA} · 방향 유지 {mono}/{kept if kept else 1}")

    # 층을 쪼개면 층마다 표본이 1/N 로 줄어 검정력이 죽는다. 층은 보존한 채 합친다.
    if len(cells_by_stratum) < 2:
        print("→ 합칠 층이 부족하다.")
        return 0
    combined = stratified_permutation_test(cells_by_stratum, runs=args.runs)
    mh = mantel_haenszel_ratio(cells_by_stratum)
    print(f"\n[층을 보존한 채 합침 — 층 안에서만 순열]")
    print(f"  고립이 위험한가  {combined.verdict.value:13s} {combined.explain()}")
    if mh:
        print(f"  단순 배율 ×{combined.lift:.2f} → 규모 통제 후 ×{mh:.2f} "
              f"— 차이만큼이 규모였다")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
