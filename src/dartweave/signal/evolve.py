"""규칙 진화 — 사람이 낸 가설 대신, 실제 결과가 채점한다.

무엇이 다른가:
  지금까지는 사람이 신호를 하나 생각해내면 우리가 검정했다. 여기서는 규칙을
  무작위로 만들어 **실제 부실 결과로 점수를 매기고**, 점수 높은 것만 남겨 섞고
  변형한다. LLM 은 채점에 들어오지 않는다 — "그럴듯한 규칙" 과 "실제로 맞는 규칙"
  은 다르고, 우리가 필요한 건 뒤쪽이다.

fitness 를 배율이 아니라 **신뢰구간 하한**으로 두는 이유:
  3사를 잡아 3사가 다 망하면 배율이 무한대다. 그게 250사를 잡아 34% 맞히는 규칙을
  이기면 안 된다. 하한을 쓰면 표본이 작을수록 하한이 저절로 내려가서, **감점 규칙을
  따로 고르지 않아도** 작은 표본이 이기지 못한다.

  임의로 "20건 미만 감점" 같은 걸 붙이면 그 20이 우리가 고른 파라미터가 되고,
  이 저장소는 그런 걸 흔들어보게 되어 있다. 하한은 고를 게 없다.

층화를 fitness 안에 넣는 이유:
  안 넣으면 진화가 **"작은 회사"** 를 찾아낸다. 작은 회사가 원래 잘 망하니까
  그게 제일 높은 점수를 받고, 우리는 규모를 신호라고 부르게 된다. 실제로 고립
  신호가 그렇게 무너진 적이 있다. 층 안에서만 비교하면 그 길이 막힌다.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass

MIN_POSITIVES = 20        # 이보다 적으면 점수를 주지 않는다 (판정 자체를 안 하는 기준과 같다)
Z = 1.96


@dataclass(frozen=True)
class Rule:
    """AND 묶음 두 개를 OR 로 잇는다. 사람이 읽을 수 있는 선까지만 복잡해진다.

    ``(("결손금", "영업CF음수"), ("CB2회이상",))`` = (결손금 AND 영업CF음수) OR CB2회이상
    """

    groups: tuple[tuple[str, ...], ...]

    def fires(self, atoms: dict[str, bool]) -> bool | None:
        """하나라도 모르는 원자가 결과를 바꿀 수 있으면 None — 모르는 걸 False 로 세지 않는다."""
        any_true = False
        any_unknown = False
        for group in self.groups:
            values = [atoms.get(a) for a in group]
            if any(v is False for v in values):
                continue                      # 이 묶음은 확실히 거짓
            if any(v is None for v in values):
                any_unknown = True
                continue
            any_true = True
        if any_true:
            return True
        return None if any_unknown else False

    def __str__(self) -> str:
        return " OR ".join(" AND ".join(g) for g in self.groups)

    @property
    def size(self) -> int:
        return sum(len(g) for g in self.groups)


def _log_ratio_lower(a: int, n1: int, b: int, n0: int) -> float:
    """위험비 95% 신뢰구간 하한 (Katz 로그 근사).

    a/n1 이 신호군, b/n0 이 비신호군이다. 어느 쪽이든 0 이면 로그가 발산하므로
    0.5 를 더한다(Haldane 보정) — 없는 걸 무한대로 만들지 않기 위해서다.
    """
    if n1 == 0 or n0 == 0:
        return 0.0
    a_, b_ = a + 0.5, b + 0.5
    rr = (a_ / (n1 + 1)) / (b_ / (n0 + 1))
    se = math.sqrt(1 / a_ - 1 / (n1 + 1) + 1 / b_ - 1 / (n0 + 1))
    return math.exp(math.log(rr) - Z * se)


def fitness(rule: Rule, cells: list[tuple[list[bool], list[bool]]]) -> float:
    """층별로 세어 합친 뒤, 배율의 신뢰구간 하한을 점수로 준다.

    층은 규모 × 업종이다. 층 안에서만 비교하므로 "작은 회사" 나 "특정 업종" 을
    찾아내는 규칙은 점수를 못 받는다.
    """
    a = n1 = b = n0 = 0
    for sig, ctl in cells:
        if not sig or not ctl:
            continue                          # 한쪽이 빈 층은 비교가 성립하지 않는다
        a += sum(sig); n1 += len(sig)
        b += sum(ctl); n0 += len(ctl)
    if a < MIN_POSITIVES:
        return 0.0
    return _log_ratio_lower(a, n1, b, n0)


def mutate(rule: Rule, atoms: list[str], rng: random.Random) -> Rule:
    """원자 하나를 바꾸거나, 붙이거나, 뗀다. 규칙이 무한히 길어지지 않게 막는다."""
    groups = [list(g) for g in rule.groups]
    move = rng.choice(("swap", "add", "drop", "split"))
    gi = rng.randrange(len(groups))
    if move == "swap" and groups[gi]:
        groups[gi][rng.randrange(len(groups[gi]))] = rng.choice(atoms)
    elif move == "add" and len(groups[gi]) < 3:
        groups[gi].append(rng.choice(atoms))
    elif move == "drop" and len(groups[gi]) > 1:
        groups[gi].pop(rng.randrange(len(groups[gi])))
    elif move == "split" and len(groups) < 2:
        groups.append([rng.choice(atoms)])
    return _normalize(groups)


def crossover(x: Rule, y: Rule, rng: random.Random) -> Rule:
    """한쪽에서 묶음 하나, 다른 쪽에서 묶음 하나를 가져온다."""
    return _normalize([list(rng.choice(x.groups)), list(rng.choice(y.groups))])


def _normalize(groups: list[list[str]]) -> Rule:
    """중복 원자·중복 묶음·빈 묶음을 지운다. 안 지우면 같은 규칙이 다른 얼굴로 번식한다."""
    seen: set[tuple[str, ...]] = set()
    for g in groups:
        key = tuple(sorted(set(g)))
        if key:
            seen.add(key)
    # 묶음 순서도 정규화한다. 안 하면 `A OR B` 와 `B OR A` 가 다른 개체로 살아남아
    # 개체군의 절반이 같은 규칙의 다른 얼굴로 채워진다 — 실측으로 상위 5개 중
    # 넷이 그랬다.
    return Rule(tuple(sorted(seen)) or (("결손금",),))


def random_rule(atoms: list[str], rng: random.Random) -> Rule:
    n = rng.choice((1, 1, 2, 2, 3))
    return _normalize([[rng.choice(atoms) for _ in range(n)]])
