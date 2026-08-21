"""이 저장소가 낸 판정 전부를 한 가족으로 묶어 다중검정 보정한다.

가족에 넣는 기준:
  **판정이 나온 검정만** — 표본 미달로 보류한 건 검정을 한 게 아니다.
  통제 설정 8개는 같은 가설의 민감도 스윕이라 하나로 센다(이미 최보수만 쓴다).
  세는 단위는 (신호 × 기준시점).

아래 목록은 손으로 옮긴 값이 아니라 각 스크립트 출력에서 그대로 가져온 것이고,
숫자를 바꾸려면 해당 스크립트를 다시 돌려 갱신해야 한다.

사용:
    uv run python scripts/adjust_multiplicity.py
"""
from __future__ import annotations

import argparse

from dartweave.signal.multiplicity import adjust

# (이름, 최보수 설정의 p, 채택 여부와 그 사유)
FAMILY = [
    ("결손금 · T=2022",            0.0002, "채택"),
    ("결손금 · T=2023",            0.0002, "채택"),
    ("부채비율 200%↑ · T=2023",     0.0004, "T=2022 표본 미달 — 한 시점뿐"),
    ("당기순손실 · T=2023",         0.0010, "T=2022 에서 탈락 — 시점 간 갈림"),
    ("영업손실 · T=2022",          0.0077, "채택"),
    ("영업손실 · T=2023",          0.0124, "채택"),
    ("당기순손실 · T=2022",         0.0586, "탈락"),
    ("고립|재무 조건부 · T=2023",    0.0620, "T=2022 와 갈림"),
    ("고립(부실 이벤트) · T=2023",   0.1070, "탈락"),
    ("고립(감사의견)",              0.1571, "탈락 — 통제하면 사라짐"),
    ("고립|재무 조건부 · T=2022",    0.6948, "탈락"),
    ("고립(부실 이벤트) · T=2022",   0.8613, "탈락 — 방향까지 반대"),
    ("공동의존점 근접",              0.0007, "탈락 — 방향이 반대"),
    ("차수(연결 수)",               0.0003, "탈락 — 공시량 층화에서 무너짐"),
]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--alpha", type=float, default=0.05)
    args = p.parse_args(argv)

    rows = adjust([(n, v) for n, v, _ in FAMILY], alpha=args.alpha)
    why = {n: w for n, _, w in FAMILY}
    m = len(rows)
    print(f"\n가족 {m}개 (판정이 나온 검정만) · alpha={args.alpha}")
    print(f"Bonferroni 임계 p = {args.alpha / m:.5f}\n")
    print(f"  {'':28s} {'p':>8s} {'BH임계':>8s}  {'Bonf':>4s} {'FDR':>4s}  사유")
    for r in rows:
        print(f"  {r.name:28s} {r.p_value:8.4f} {r.threshold:8.5f}  "
              f"{'○' if r.bonferroni else '×':>4s} {'○' if r.fdr else '×':>4s}  "
              f"{why[r.name]}")

    surv_b = [r.name for r in rows if r.bonferroni]
    surv_f = [r.name for r in rows if r.fdr]
    print(f"\n  Bonferroni 통과 {len(surv_b)}건: {', '.join(surv_b)}")
    print(f"  BH(FDR) 통과 {len(surv_f)}건: {', '.join(surv_f)}")
    print("\n  ※ 작은 p 가 곧 채택은 아니다. 공동의존점 근접(p=0.0007)과 차수(p=0.0003)는"
          "\n     보정을 통과하지만 방향이 반대이거나 층화에서 무너져 채택하지 않았다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
