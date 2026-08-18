"""신호 검정 — "이 신호를 가진 기업은 이후 부실이 유의하게 많은가".

왜 모델이 아니라 검정인가:
  실측상 부실 라벨이 연 90건이다(2024, 해산 제외). 특징 수십 개짜리 예측 모델은
  과적합이 확정적이다. 특징 **하나씩** 검정하면 이 표본으로도 답할 수 있다.

무엇을 지키나:
  1. 특징은 T 이전, 라벨은 T 이후 — `db/asof.py` 가 강제한다.
  2. 유의성은 귀무 대조로 본다. 층1이 모듈러리티에 절대 기준을 안 쓴 것과 같다 —
     "신호군의 부실률 12%" 는 그 자체로 아무 뜻이 없고, 비신호군이 몇 %인지가 있어야 한다.
  3. 못 정하면 `결론 없음` 을 돌려준다. 예외가 아니라 정식 반환값이다.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from enum import Enum

MIN_POSITIVES = 20   # 신호군 부실 사례가 이보다 적으면 판정 자체를 안 한다
DEFAULT_RUNS = 2000  # 순열 반복


class Verdict(Enum):
    SUPPORTED = "supported"          # 신호군 부실률이 유의하게 높다
    NO_DIFFERENCE = "no_difference"  # 차이가 우연과 구분되지 않는다
    TOO_FEW = "too_few"              # 표본이 부족해 판정 불가


@dataclass(frozen=True)
class SignalResult:
    verdict: Verdict
    signal_n: int
    signal_events: int
    control_n: int
    control_events: int
    p_value: float | None
    runs: int

    @property
    def signal_rate(self) -> float:
        return self.signal_events / self.signal_n if self.signal_n else 0.0

    @property
    def control_rate(self) -> float:
        return self.control_events / self.control_n if self.control_n else 0.0

    @property
    def lift(self) -> float | None:
        """신호군이 비신호군의 몇 배인가. 비율만 보면 기저율을 못 본다."""
        c = self.control_rate
        return (self.signal_rate / c) if c else None

    def explain(self) -> str:
        if self.verdict is Verdict.TOO_FEW:
            return (f"판정 불가 — 신호군 부실 {self.signal_events}건 "
                    f"(최소 {MIN_POSITIVES}건 필요)")
        x = f"×{self.lift:.2f}" if self.lift else "배율 산출 불가"
        return (f"신호군 {self.signal_rate:.1%} ({self.signal_events}/{self.signal_n}) vs "
                f"비신호군 {self.control_rate:.1%} ({self.control_events}/{self.control_n}) "
                f"— {x} · p={self.p_value:.4f} · 순열 {self.runs:,}회")


def permutation_test(
    signal: list[bool], control: list[bool], *, runs: int = DEFAULT_RUNS, seed: int = 1
) -> SignalResult:
    """두 군의 부실률 차이가 우연으로 나올 수 있는가.

    라벨을 무작위로 섞어 같은 크기로 나눴을 때, 관측된 차이 이상이 몇 번 나오는지 센다.
    분포 가정을 안 해서 작은 표본에도 쓸 수 있다 — 우리 상황이 정확히 그렇다.
    """
    sn, cn = len(signal), len(control)
    se, ce = sum(signal), sum(control)
    if se < MIN_POSITIVES:
        return SignalResult(Verdict.TOO_FEW, sn, se, cn, ce, None, 0)

    observed = (se / sn) - (ce / cn)
    pool = signal + control
    rng = random.Random(seed)
    hits = 0
    for _ in range(runs):
        rng.shuffle(pool)
        diff = (sum(pool[:sn]) / sn) - (sum(pool[sn:]) / cn)
        if diff >= observed:
            hits += 1
    p = (hits + 1) / (runs + 1)   # +1 보정 — p=0 은 "불가능" 이 아니라 "못 봤다" 다
    verdict = Verdict.SUPPORTED if p < 0.05 else Verdict.NO_DIFFERENCE
    return SignalResult(verdict, sn, se, cn, ce, p, runs)
