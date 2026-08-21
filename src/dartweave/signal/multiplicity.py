"""다중검정 보정 — 많이 재면 하나쯤은 우연히 유의해진다.

왜 필요한가:
  이 저장소는 신호를 수십 번 검정했다. p<0.05 를 그대로 쓰면, 20번 재서 하나
  걸리는 건 우연으로도 일어난다. 여덟 번이나 교란을 잡아낸 저장소가 정작 이걸
  안 잡으면 앞뒤가 안 맞는다.

무엇을 가족(family)으로 묶나:
  **가설 하나당 하나**다. 통제 설정 8개를 흔든 건 서로 다른 가설을 8번 검정한 게
  아니라 **같은 가설의 민감도 스윕**이고, 우리는 이미 그중 가장 보수적인 답만
  결론으로 쓴다. 설정까지 세어 156으로 나누면 과보정이다.

  세는 단위: (신호 × 기준시점). 판정이 나온 것만 — 표본 미달로 판정을 보류한 건
  검정을 한 게 아니다.

두 가지를 같이 낸다:
  Bonferroni  가장 보수적. 하나라도 거짓 양성을 내지 않는 데 초점.
  BH (FDR)    거짓 양성 **비율**을 통제. 신호를 훑어보는 상황의 표준이다.

작은 p 가 곧 채택은 아니다. 방향이 반대이거나 기준시점 간 재현이 안 되면 p 와
무관하게 떨어진다 — 이 모듈은 그중 '우연히 작은 p' 만 걸러낸다.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Adjusted:
    name: str
    p_value: float
    bonferroni: bool     # 가족 전체에서 하나의 거짓 양성도 허용하지 않는 기준
    fdr: bool            # 거짓 양성 비율을 alpha 이하로 유지하는 기준
    rank: int
    threshold: float     # 이 항목에 적용된 BH 임계


def adjust(pairs: list[tuple[str, float]], *, alpha: float = 0.05) -> list[Adjusted]:
    """(이름, p) 목록을 받아 Bonferroni · BH 통과 여부를 매긴다.

    BH 는 **아래에서 위로** 판정한다. p 를 오름차순으로 놓고 `p(i) <= i·alpha/m` 을
    만족하는 **가장 큰 i** 를 찾아, 그 아래(1..i) 를 전부 기각한다. 항목마다 따로
    비교하면 중간에 하나 어긋났을 때 그 아래까지 잃는다.
    """
    m = len(pairs)
    if not m:
        return []
    ordered = sorted(pairs, key=lambda x: x[1])
    cut = 0
    for i, (_, p) in enumerate(ordered, 1):
        if p <= i * alpha / m:
            cut = i
    bonf = alpha / m
    return [
        Adjusted(name=name, p_value=p, bonferroni=p <= bonf, fdr=i <= cut,
                 rank=i, threshold=i * alpha / m)
        for i, (name, p) in enumerate(ordered, 1)
    ]
