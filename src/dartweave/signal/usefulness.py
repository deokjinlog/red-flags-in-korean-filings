"""신호가 유의한 것과 쓸 만한 것은 다른 말이다.

왜 이게 따로 필요한가:
  결손금은 ×3.7 · p=0.0002 로 이 저장소에서 가장 강한 신호다. 그런데 그 말을
  "결손금 있으면 망한다" 로 읽으면 완전히 틀린다. **결손 기업의 94%는 2년 안에
  아무 일도 없었다.** 배율은 기저율 위에서만 뜻이 있고, 기저율이 3% 면 ×3.7 은
  6% 다. 6% 는 여전히 "대부분 아니다" 다.

  반대쪽도 봐야 한다. 부실이 난 회사 중 몇 %가 이 신호에 걸렸는가(재현율).
  절반을 놓치는 신호를 "부실을 잡아낸다" 고 말하면 안 된다.

  유의성 검정은 "차이가 우연이 아니다" 까지만 말한다. 그 차이로 **무엇을 할 수
  있는가** 는 정밀도·재현율이 답한다. 둘을 같이 내지 않으면 배율이 과장된다.

⚠️ 여기 배율은 `signal/test.py` 의 배율과 **분모가 다르다.**
  검정 쪽 ×3.70 은 신호군 대 **비신호군**이고 규모·업종을 통제한 값이다.
  여기 ×2.10 은 신호군 대 **전체**(신호군 포함)이고 통제가 없다. 전체를 분모로
  쓰면 신호군이 분모에 섞여 배율이 낮게 나온다. 둘 다 맞고, 답하는 질문이 다르다 —
  검정 쪽은 "우연인가", 이쪽은 "그래서 무엇을 할 수 있는가".

부트스트랩 신뢰구간을 같이 내는 이유:
  점추정 하나만 내면 ×3.7 이 확정된 값처럼 읽힌다. 표본을 다시 뽑으면 얼마나
  움직이는지가 있어야 "×3~4 사이" 라고 말할 수 있다.
"""
from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass(frozen=True)
class Usefulness:
    flagged: int          # 신호에 걸린 기업 수
    total: int            # 전체 기업 수
    caught: int           # 걸린 기업 중 실제로 부실이 난 수
    events: int           # 전체 부실 기업 수

    @property
    def flagged_share(self) -> float:
        """전체의 몇 %를 걸러내는가. 너무 넓으면 실용성이 없다."""
        return self.flagged / self.total if self.total else 0.0

    @property
    def precision(self) -> float:
        """걸린 기업 중 실제로 부실이 난 비율."""
        return self.caught / self.flagged if self.flagged else 0.0

    @property
    def recall(self) -> float:
        """부실 기업 중 이 신호에 걸린 비율. 놓친 쪽을 봐야 한다."""
        return self.caught / self.events if self.events else 0.0

    @property
    def base_rate(self) -> float:
        return self.events / self.total if self.total else 0.0

    @property
    def lift(self) -> float | None:
        return self.precision / self.base_rate if self.base_rate else None

    def explain(self) -> str:
        return (
            f"걸림 {self.flagged:,}/{self.total:,}사({self.flagged_share:.0%}) · "
            f"그중 부실 {self.caught}사({self.precision:.1%}) — "
            f"**{1 - self.precision:.0%}는 아무 일도 없었다** · "
            f"부실 {self.events}사 중 {self.caught}사를 잡음(재현율 {self.recall:.0%}) · "
            f"기저율 {self.base_rate:.1%} 대비 ×{self.lift:.2f}"
            if self.lift else "산출 불가"
        )


def usefulness(flags: list[bool], labels: list[bool]) -> Usefulness:
    """같은 순서의 (신호 여부, 부실 여부) 두 목록에서 정밀도·재현율을 낸다."""
    if len(flags) != len(labels):
        raise ValueError("두 목록의 길이가 달라 짝이 어긋난다")
    return Usefulness(
        flagged=sum(flags),
        total=len(flags),
        caught=sum(1 for f, y in zip(flags, labels) if f and y),
        events=sum(labels),
    )


def lift_ci(
    flags: list[bool], labels: list[bool], *,
    runs: int = 2000, alpha: float = 0.05, seed: int = 1,
) -> tuple[float, float] | None:
    """배율의 부트스트랩 신뢰구간.

    기업을 복원추출로 다시 뽑아 배율을 매번 다시 계산한다. 점추정 하나만 내면
    ×3.7 이 확정된 값처럼 읽히는데, 실제로는 표본을 다시 뽑으면 움직인다.
    """
    n = len(flags)
    if n == 0:
        return None
    rng = random.Random(seed)
    pairs = list(zip(flags, labels))
    out: list[float] = []
    for _ in range(runs):
        sample = [pairs[rng.randrange(n)] for _ in range(n)]
        u = usefulness([f for f, _ in sample], [y for _, y in sample])
        if u.lift is not None:
            out.append(u.lift)
    if not out:
        return None
    out.sort()
    lo = out[int(len(out) * alpha / 2)]
    hi = out[min(len(out) - 1, int(len(out) * (1 - alpha / 2)))]
    return lo, hi
