"""렌즈 — "무엇을 보고 싶은가" 의 선언.

관계 타입을 **살리거나 죽이거나**만 한다. 중간값 튜닝을 하지 않는 이유는
`왜 0.1인데요?` 에 답할 방법이 없기 때문이다. 임의성을 이진 선택 하나로 격리한다.
"""
from __future__ import annotations

from dataclasses import dataclass


# ⚠️ RISK(breaking): 여기에 가중치 계수 필드를 추가하면 AC-1 이 무너진다. 렌즈가
# 이진 선택을 넘어 튜닝 가능한 값을 갖는 순간 "왜 0.1인데요?" 에 답할 근거가 사라지고,
# 결론이 데이터가 아니라 손으로 고른 상수에서 나오게 된다. 필드 집합은
# tests/structure/test_lens.py::test_lens_holds_only_include_list 이 고정하고 있다.
# — by main(3-checklist: 공개 스키마 변경)
@dataclass(frozen=True)
class Lens:
    name: str
    include: frozenset[str]


LENSES: dict[str, Lens] = {
    "supply": Lens("supply", frozenset({"SUPPLIES_TO", "PRODUCES"})),
    "governance": Lens(
        "governance",
        frozenset({"MAJOR_SHAREHOLDER_OF", "INVESTS_IN", "HOLDS_5PCT"}),
    ),
    "people": Lens("people", frozenset({"EXECUTIVE_OF"})),
}


def resolve_lens(name: str) -> Lens:
    if name not in LENSES:
        raise ValueError(f"알 수 없는 렌즈 '{name}'. 가능한 값: {', '.join(LENSES)}")
    return LENSES[name]


def select_indices(edges: list[tuple[str, str, str]], lens: Lens) -> list[int]:
    """살아남는 엣지의 인덱스. 평행 리스트(근거·가중치)를 같이 거르기 위한 것."""
    return [i for i, e in enumerate(edges) if e[2] in lens.include]


def apply_lens(
    edges: list[tuple[str, str, str]], lens: Lens
) -> list[tuple[str, str, str]]:
    return [edges[i] for i in select_indices(edges, lens)]
