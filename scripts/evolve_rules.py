"""규칙을 진화시켜 찾고, 손 안 댄 표본에서 한 번 확정한다.

왜 표본을 가르나:
  진화는 수천 개 규칙을 시도한다. 그걸 우리 검정 틀에 그냥 얹으면 **다중검정이
  폭발한다** — 지금 가족 52개에 Bonferroni 임계가 0.00096 인데, 규칙 수천 개를
  시도하면 그중 최고점은 거의 확실히 우연이다. 유전 알고리즘의 고전적 함정이고,
  이 저장소가 여덟 번 무너진 것과 같은 종류다.

  그래서 가른다:

      탐색  T=2021·2022 — 여기서는 몇천 번 시도해도 된다
      확정  T=2023·2024 — 탐색 중 한 번도 안 본다. 최종 후보 몇 개만 여기서 잰다

  확정 표본을 한 번도 안 봤으니 과적합이 통하지 않고, 다중검정 가족은 **최종 후보
  개수만큼만** 커진다.

fitness 는 층화 배율의 신뢰구간 하한이다 — `signal/evolve.py` 참조. 층은 규모 ×
업종이라 "작은 회사" 나 "특정 업종" 을 찾아내는 규칙은 점수를 못 받는다.

사용:
    uv run python scripts/evolve_rules.py --generations 40
"""
from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from dartweave.db.asof import events_after
from dartweave.signal.evolve import (
    MIN_POSITIVES,
    Rule,
    crossover,
    fitness,
    mutate,
    random_rule,
)
from dartweave.signal.labels import is_distress
from dartweave.signal.test import (
    Verdict,
    mantel_haenszel_ratio,
    stratified_permutation_test,
)
from test_financial_signals import SIGNALS_ORDER, build_features

N_STRATA, INDUSTRY_DIGITS = 4, 1


def load(as_of: list[str], within_days: int):
    """기준시점별 (원자 표, 라벨, 자산, 업종)."""
    industry = {k: str(v) for k, v in
                json.loads(Path("data/industry.json").read_text(encoding="utf-8")).items()
                if v}
    engine = create_engine("sqlite:///data/timeseries.db")
    out = []
    for T in as_of:
        with Session(engine) as s:
            events = events_after(s, T, within_days=within_days)
        label = {e.corp_code for e in events if is_distress(e.event_type)}
        feats, assets = build_features(T)
        pool = [c for c in feats if c in industry and c in assets]
        out.append((T, {c: feats[c] for c in pool}, label, assets, industry))
    return out


def cells_for(rule: Rule, feats, label, assets, industry):
    """자산 층 × 업종 교차 셀. 모르는 회사는 아예 뺀다 — 안전한 쪽으로 세지 않는다."""
    codes = [c for c in feats if rule.fires(feats[c]) is not None]
    codes.sort(key=lambda c: assets[c])
    size = max(1, len(codes) // N_STRATA)
    buckets = defaultdict(list)
    for i in range(N_STRATA):
        chunk = codes[i * size:] if i == N_STRATA - 1 else codes[i * size:(i + 1) * size]
        for c in chunk:
            buckets[(i, industry[c][:INDUSTRY_DIGITS])].append(c)
    return [([c in label for c in g if rule.fires(feats[c])],
             [c in label for c in g if not rule.fires(feats[c])])
            for g in buckets.values()]


def score(rule: Rule, frames) -> float:
    """탐색 시점 전부에서 점수를 받아야 한다 — 최솟값을 쓴다.

    평균을 쓰면 한 시점에서만 좋은 규칙이 살아남는다. 우리가 신호를 채택할 때
    "모든 기준시점에서" 를 요구하는 것과 같은 규율이다.
    """
    return min(fitness(rule, cells_for(rule, f, lb, a, ind))
               for _, f, lb, a, ind in frames)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--train", default="20210630,20220630")
    p.add_argument("--holdout", default="20230630,20240630")
    p.add_argument("--within-days", type=int, default=730)
    p.add_argument("--population", type=int, default=120)
    p.add_argument("--generations", type=int, default=40)
    p.add_argument("--finalists", type=int, default=5)
    p.add_argument("--runs", type=int, default=4000)
    p.add_argument("--seed", type=int, default=1)
    args = p.parse_args(argv)

    rng = random.Random(args.seed)
    train = load([x.strip() for x in args.train.split(",")], args.within_days)
    atoms = list(SIGNALS_ORDER)
    print(f"원자 {len(atoms)}종 · 탐색 시점 {', '.join(t for t, *_ in train)}")

    pop = [random_rule(atoms, rng) for _ in range(args.population)]
    best_seen: dict[str, float] = {}
    for gen in range(args.generations):
        scored = sorted(((score(r, train), r) for r in pop),
                        key=lambda x: -x[0])
        for s, r in scored:
            best_seen[str(r)] = max(best_seen.get(str(r), 0.0), s)
        elite = [r for _, r in scored[: args.population // 4]]
        pop = list(elite)
        while len(pop) < args.population:
            if rng.random() < 0.5:
                pop.append(mutate(rng.choice(elite), atoms, rng))
            else:
                pop.append(crossover(rng.choice(elite), rng.choice(elite), rng))
        if gen % 10 == 0 or gen == args.generations - 1:
            print(f"  세대 {gen:3d} · 최고 {scored[0][0]:.2f} · {scored[0][1]}", flush=True)

    ranked = sorted(best_seen.items(), key=lambda kv: -kv[1])
    print(f"\n탐색 결과 상위 {args.finalists}개 (fitness = 층화 배율의 95% 하한)")
    finalists = []
    for name, s in ranked[: args.finalists]:
        groups = tuple(tuple(g.split(" AND ")) for g in name.split(" OR "))
        finalists.append(Rule(groups))
        print(f"  {s:5.2f}  {name}")

    print(f"\n{'=' * 70}\n확정 — 손 안 댄 표본 {args.holdout} 에서 딱 한 번")
    hold = load([x.strip() for x in args.holdout.split(",")], args.within_days)
    for rule in finalists:
        line = []
        for T, f, lb, a, ind in hold:
            cells = cells_for(rule, f, lb, a, ind)
            r = stratified_permutation_test(cells, runs=args.runs)
            mh = mantel_haenszel_ratio(cells)
            n = sum(1 for c in f if rule.fires(f[c]))
            if r.verdict is Verdict.TOO_FEW:
                line.append(f"{T[:4]} 표본미달")
            else:
                line.append(f"{T[:4]} ×{mh:.2f} p={r.p_value:.4f} "
                            f"{'채택' if r.verdict is Verdict.SUPPORTED else '탈락'}"
                            f"({n}사)")
        print(f"  {rule}\n     {' · '.join(line)}")
    print(f"\n다중검정 가족은 최종 후보 {len(finalists)}개 × 확정 시점 "
          f"{len(hold)}개 = {len(finalists) * len(hold)}건만 늘어난다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
