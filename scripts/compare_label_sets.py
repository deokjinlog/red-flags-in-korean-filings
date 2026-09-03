"""라벨 집합 두 벌을 나란히 놓는다 — 어느 쪽도 '정답' 이 아니다.

왜 두 벌인가:
  부도·회생·상장폐지는 **되돌릴 수 없는** 사건이다. 관리종목 지정은 다르다 —
  해제가 311건 있다. 둘을 한 덩어리로 섞으면 "부실" 이라는 말이 조용히 바뀌고
  지금까지 잰 모든 배율이 다른 뜻이 된다.

  그렇다고 넓은 쪽을 버릴 이유도 없다. 라벨이 529 → 899건으로 늘면 검정력이 올라가
  **판정 자체가 안 나던 신호들이 답을 낸다.** 답이 "채택" 일 수도 "탈락" 일 수도 있고,
  둘 다 몰랐던 것보다 낫다.

  그래서 둘 다 돌리고 둘 다 낸다. 하나만 쓰면 그게 유리해서 골랐는지 알 수 없다.

읽는 법:
  · 양쪽 모두 채택   — 가장 견고하다. 라벨 정의가 바뀌어도 살아남았다.
  · 넓은 쪽만 채택   — 신호가 강해진 게 아니라 **검정력이 올라간** 것이다.
                      동시에 "부실" 의 뜻도 달라졌다는 걸 같이 읽어야 한다.
  · 넓은 쪽에서 탈락 — 좁은 쪽에서 "판정 불가" 였던 게 이제 아니라고 답한 것이다.

사용:
    uv run python scripts/compare_label_sets.py
"""
from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path

BASES = ("20230630", "20240630")


def load(path: str) -> dict[str, dict]:
    rows = json.loads(Path(path).read_text(encoding="utf-8"))
    by: dict[str, dict] = collections.defaultdict(dict)
    for r in rows:
        by[r["signal"]][r["as_of"]] = r
    return by


def state(by: dict[str, dict], key: str) -> tuple[str, str]:
    """(등급, 표시 문자열). 등급은 정렬에 쓴다."""
    v = by.get(key, {})
    ok = [a for a in BASES if v.get(a, {}).get("verdict") == "채택"]
    if len(ok) == len(BASES):
        lo = min(v[a]["ratio"] for a in ok)
        hi = max(v[a]["ratio"] for a in ok)
        return "채택", f"채택 2/2 ×{lo:.2f}~{hi:.2f}"
    if ok:
        return "부분", f"판정 1/2 ×{v[ok[0]]['ratio']:.2f}"
    if any(v.get(a, {}).get("verdict") == "탈락" for a in BASES):
        return "탈락", "탈락"
    return "미판정", "판정 불가"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="data/signal_results.json")
    p.add_argument("--warning", default="data/signal_results_warning.json")
    args = p.parse_args(argv)

    base, warn = load(args.base), load(args.warning)
    order = {"채택": 0, "부분": 1, "탈락": 2, "미판정": 3}
    keys = sorted(set(base) | set(warn),
                  key=lambda k: (order[state(base, k)[0]], order[state(warn, k)[0]], k))

    print(f"{'신호':<26}{'부실만':<24}{'+관리종목':<24}")
    print("─" * 78)
    moved = 0
    for k in keys:
        (bg, bs), (wg, ws) = state(base, k), state(warn, k)
        note = ""
        if bg != "채택" and wg == "채택":
            note, moved = "  ← 라벨을 넓히니 판정이 났다", moved + 1
        elif bg == "미판정" and wg == "탈락":
            note, moved = "  ← 이제 아니라고 답한다", moved + 1
        print(f"{k:<26}{bs:<24}{ws:<24}{note}")

    both = [k for k in keys if state(base, k)[0] == state(warn, k)[0] == "채택"]
    print(f"\n양쪽 모두 채택 {len(both)}종 — 라벨 정의가 바뀌어도 살아남은 것들")
    print(f"넓은 쪽에서만 답이 난 신호 {moved}종")
    print("\n⚠️ 넓은 쪽 배율이 전반적으로 낮다. 신호가 약해진 게 아니라 기저율이"
          " 높아져서다\n   (T=2024 2.36% → 4.41%). 배율은 기저율 대비 값이다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
