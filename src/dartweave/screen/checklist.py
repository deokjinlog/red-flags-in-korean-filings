"""종목 하나의 "사지 말 이유" 체크리스트 — 판정 대신 위치를 낸다.

왜 판정을 안 하나:
  걸린 것의 90%는 2년 안에 아무 일도 없었다. 그 숫자를 알면서 "위험" 이라고 쓰면
  거짓말이다. 대신 **어느 구간에 있는지**와 **그 구간의 실측 부실률**을 낸다.

무엇을 반드시 같이 내나:
  걸린 것만 보여주면 균형이 깨진다. 그래서 네 덩어리를 다 낸다 —
  걸린 것 / 안 걸린 것 / 검정을 못 통과한 것 / **우리가 아예 못 본 것**.

  마지막이 제일 중요하다. 주석·담보·소송·조항 본문은 우리가 안 읽는다. 그걸 안
  적으면 읽는 사람이 "이 체크리스트를 통과했으니 괜찮다" 로 읽는다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from dartweave.screen.flags import (
    ADOPTED_KINDS,
    Flag,
    flag_count_summary,
    is_adopted,
    verification_of,
)

# 우리가 읽지 않는 것. 사람이 원문에서 직접 봐야 한다.
NOT_CHECKED: tuple[tuple[str, str], ...] = (
    ("주석 · 우발부채", "지급보증·계류 중 소송 — 부외부채는 숫자표에 안 나온다"),
    ("담보 제공 자산", "자산이 죄다 담보면 청산가치가 없다. 채권최고액 대비 여력을 봐야 한다"),
    ("특수관계자 거래", "대여금·자금거래·일감몰아주기. 금액은 본문에만 있다"),
    ("핵심감사사항(KAM)", "감사인이 '이게 제일 위험하다' 고 콕 집은 것"),
    ("CB 조항 본문", "리픽싱 하한·풋옵션 행사일. 오버행 비율만 검정됐고 나머지는 못 잰다"),
    ("계정 사이의 연결", "예: 개발비 자산화액이 자본총계보다 큰가 — 우리는 계정을 하나씩만 본다"),
)

# 원문에서 사람이 볼 자리.
WHERE_TO_READ: tuple[tuple[str, str], ...] = (
    ("조달 이력", "III. 재무에 관한 사항 → 증권의 발행을 통한 자금조달"),
    ("미상환 사채", "같은 절 → 미상환 전환사채 발행현황"),
    ("담보·보증", "연결재무제표 주석 → 우발상황 및 약정사항"),
    ("감사인 의견", "공시뷰어 첨부 → 감사보고서 / 검토보고서"),
    ("최근 1년 공시", "공시통합검색 → 회사명 · 기간 1년 · 제목만 훑기"),
)


@dataclass
class Checklist:
    name: str
    corp_code: str
    fiscal_year: str
    fired: list[Flag] = field(default_factory=list)          # 걸린 채택 신호
    clear: list[str] = field(default_factory=list)           # 안 걸린 채택 신호
    unknown: list[str] = field(default_factory=list)         # 판정 못 한 채택 신호
    reference: list[Flag] = field(default_factory=list)      # 검정 미통과 · 참고

    @property
    def summary(self) -> str:
        known = len(self.fired) + len(self.clear)
        return flag_count_summary(len(self.fired), known)


def build(name: str, corp_code: str, fiscal_year: str, flags: list[Flag],
          known: dict[str, bool | None]) -> Checklist:
    """`screen()` 결과를 네 덩어리로 가른다.

    `known` 은 채택 신호별 판정 결과다(True/False/None). **걸린 것만으로는 부족하다** —
    안 걸린 것과 판정 못 한 것을 구분해야 "0개 걸림" 이 안전을 뜻하는지 알 수 있다.
    """
    fired = [f for f in flags if is_adopted(f.kind)]
    fired_kinds = {f.kind for f in fired}
    return Checklist(
        name=name,
        corp_code=corp_code,
        fiscal_year=fiscal_year,
        fired=fired,
        clear=[k for k in ADOPTED_KINDS
               if k not in fired_kinds and known.get(k) is False],
        unknown=[k for k in ADOPTED_KINDS
                 if k not in fired_kinds and known.get(k) is None],
        reference=[f for f in flags if not is_adopted(f.kind)],
    )


def evidence_of(flag: Flag) -> tuple[list[str], str]:
    """근거 줄과 검정 상태를 가른다. 검정 상태는 `screen()` 이 마지막 줄에 붙인다."""
    lines = [e for e in flag.evidence if not e.startswith("└")]
    verdict = next((e[1:].strip() for e in flag.evidence if e.startswith("└")),
                   verification_of(flag.kind))
    return lines, verdict
