"""파이프라인 단계 정의.

각 단계는 독립 실행 가능하고, 앞 단계가 실패해도 뒤 단계가 이미 만든
산출물은 살아남는다. 재개 기준점은 Postgres 원장이다 (D4).
"""
from __future__ import annotations

from enum import Enum


class Stage(Enum):
    SELECT = "select"
    COLLECT = "collect"
    PARSE = "parse"
    RESOLVE = "resolve"
    LOAD = "load"
    TRUST = "trust"
    EXPORT = "export"


STAGES: tuple[Stage, ...] = (
    Stage.SELECT,
    Stage.COLLECT,
    Stage.PARSE,
    Stage.RESOLVE,
    Stage.LOAD,
    Stage.TRUST,
    Stage.EXPORT,
)


def resolve_stage(name: str) -> Stage:
    for s in STAGES:
        if s.value == name:
            return s
    available = ", ".join(s.value for s in STAGES)
    raise ValueError(f"알 수 없는 단계 '{name}'. 가능한 값: {available}")


def stages_from(start: Stage) -> list[Stage]:
    idx = STAGES.index(start)
    return list(STAGES[idx:])
