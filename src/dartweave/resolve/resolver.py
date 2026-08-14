"""이름 → corp_code 해소.

원칙 (AC-10): **미해소는 신규 노드를 만들지 않는다.** 대기열로 보내고 센다.
침묵 생성이 그래프 오염의 가장 흔한 경로다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from dartweave.resolve.classify import EntityKind, classify_name
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
    # 법인/자연인 분리 집계 — 개인은 corp_code 가 없어 미해소가 정상이므로
    # 전체 해소율을 품질 임계로 쓰면 정상 상태를 불합격 처리한다.
    _corp_attempts: int = 0
    _corp_hits: int = 0
    _natural: int = 0
    _unknown: int = 0

    def __post_init__(self) -> None:
        self._by_norm = {normalize_name(k): v for k, v in self.official.items()}

    def resolve(self, surface_form: str, *, rcept_no: str) -> ResolveResult:
        self._attempts += 1
        key = normalize_name(surface_form)
        code = self._by_norm.get(key) or self.aliases.get(key)
        if code:
            # 해소됐다는 건 corpCode 등재 법인이라는 뜻 — 정의상 확정이다.
            self._hits += 1
            self._corp_attempts += 1
            self._corp_hits += 1
            return ResolveResult(surface_form, code, Resolution.RESOLVED)

        kind = classify_name(surface_form)
        if kind is EntityKind.CORPORATE:
            self._corp_attempts += 1  # 법인인데 미해소 = 진짜 문제
        elif kind is EntityKind.NATURAL:
            self._natural += 1  # 개인은 corp_code 가 없다 — 미해소가 정상
        else:
            self._unknown += 1

        for rec in self.unresolved:
            if rec.surface_form == surface_form:
                rec.occurrences += 1
                break
        else:
            self.unresolved.append(UnresolvedRecord(surface_form, rcept_no))
        return ResolveResult(surface_form, None, Resolution.UNRESOLVED)

    def resolution_rate(self) -> float:
        """전체 해소율. **품질 임계로 쓰지 말 것** — 개인 주주가 분모에 섞인다."""
        return self._hits / self._attempts if self._attempts else 0.0

    def corporate_resolution_rate(self) -> float:
        """법인 후보 중 해소된 비율. **이게 품질 게이트가 봐야 할 값이다.**

        실측(삼성전자·SK하이닉스): 전체 29.7% 였지만 그 대부분은 홍라희·이재용 같은
        개인 주주라 미해소가 정상이었다. 법인만 보면 실제 매핑 품질이 드러난다.
        """
        return self._corp_hits / self._corp_attempts if self._corp_attempts else 0.0

    def breakdown(self) -> dict[str, int | float]:
        """해소 결과 분해. 게이트 판정과 보고에 함께 쓴다."""
        return {
            "attempts": self._attempts,
            "corporate_attempts": self._corp_attempts,
            "corporate_resolved": self._corp_hits,
            "corporate_unresolved": self._corp_attempts - self._corp_hits,
            "natural_person": self._natural,
            "unknown": self._unknown,
            "corporate_resolution_rate": self.corporate_resolution_rate(),
            "overall_resolution_rate": self.resolution_rate(),
        }
