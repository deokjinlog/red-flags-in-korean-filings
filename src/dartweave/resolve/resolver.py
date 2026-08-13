"""이름 → corp_code 해소.

원칙 (AC-10): **미해소는 신규 노드를 만들지 않는다.** 대기열로 보내고 센다.
침묵 생성이 그래프 오염의 가장 흔한 경로다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from dartweave.resolve.normalize import normalize_name


class Resolution(Enum):
    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class ResolveResult:
    surface_form: str
    corp_code: str | None
    status: Resolution


@dataclass
class UnresolvedRecord:
    surface_form: str
    rcept_no: str
    occurrences: int = 1


@dataclass
class Resolver:
    official: dict[str, str]
    aliases: dict[str, str]
    unresolved: list[UnresolvedRecord] = field(default_factory=list)
    _attempts: int = 0
    _hits: int = 0

    def __post_init__(self) -> None:
        self._by_norm = {normalize_name(k): v for k, v in self.official.items()}

    def resolve(self, surface_form: str, *, rcept_no: str) -> ResolveResult:
        self._attempts += 1
        key = normalize_name(surface_form)
        code = self._by_norm.get(key) or self.aliases.get(key)
        if code:
            self._hits += 1
            return ResolveResult(surface_form, code, Resolution.RESOLVED)

        for rec in self.unresolved:
            if rec.surface_form == surface_form:
                rec.occurrences += 1
                break
        else:
            self.unresolved.append(UnresolvedRecord(surface_form, rcept_no))
        return ResolveResult(surface_form, None, Resolution.UNRESOLVED)

    def resolution_rate(self) -> float:
        return self._hits / self._attempts if self._attempts else 0.0
