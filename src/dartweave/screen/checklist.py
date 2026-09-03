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
    audit_split,
    direction_split,
    disclosure_split,
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

# 신호마다 DART 어디를 여는지. 수기 점검표가 항목마다 이 칸을 둔 이유가 있다 —
# "봐야 한다" 는 알겠는데 어디를 여는지 모르면 못 본다.
WHERE_IN_DART: dict[str, str] = {
    "결손금": "III. 재무 → 연결 재무상태표 → 이익잉여금(결손금)",
    "영업손실": "III. 재무 → 연결 포괄손익계산서 → 영업이익",
    "당기순손실": "III. 재무 → 연결 포괄손익계산서 → 당기순이익(손실)",
    "영업현금흐름 음수": "III. 재무 → 연결 현금흐름표 → 영업활동현금흐름",
    "이자보상배율 1 미만": "포괄손익계산서 영업이익 ÷ 현금흐름표 이자의 지급",
    "최근 3년 CB·BW 발행": "공시통합검색 → 주요사항보고서 → 전환사채권 발행결정",
    "최근 3년 CB·BW 2회 이상": "같은 곳 — 최근 3년 건수를 센다",
    "최대주주 변경 최근 3년": "정기보고서 → VII. 주주에 관한 사항 → 최대주주 변동현황",
}


# 항목이 **무엇인지** 한 줄. 판정 결과만 있고 용어 설명이 없으면, 용어를 아는
# 사람만 읽을 수 있는 리포트가 된다 — 그건 이 도구가 없애려던 문턱이다.
#
# 회계 정의를 그대로 옮기지 않는다. "이익잉여금의 부(-)의 잔액" 은 정확하지만
# 모르는 사람에게 아무것도 알려주지 않는다. 무엇을 뜻하는지를 쓴다.
WHAT_IT_IS: dict[str, str] = {
    "결손금":
        "회사를 세운 뒤로 번 돈과 잃은 돈을 전부 합쳤더니 마이너스라는 뜻입니다. "
        "한 해 실적이 아니라 **누적**이라, 나쁜 해가 여러 번 쌓였거나 크게 한 번 "
        "무너졌다는 신호입니다. 쌓아 둔 완충이 없다는 뜻이기도 합니다.",
    "당기순손실":
        "한 해를 결산했더니 손해였다는 뜻입니다. 본업뿐 아니라 이자·환차손·자산 "
        "평가손까지 전부 넣은 **맨 마지막 숫자**입니다.",
    "영업손실":
        "본업에서 손해가 났다는 뜻입니다. 이자나 환율 같은 바깥 사정을 빼고 "
        "**팔아서 남았는가**만 본 숫자라, 밖을 탓해서 설명되지 않습니다.",
    "영업현금흐름 음수":
        "한 해 동안 본업에서 현금이 나가기만 했다는 뜻입니다. 이익에는 회계 추정이 "
        "들어가지만 **현금은 들어오거나 안 들어오거나 둘 중 하나**라, 장부상 흑자인데 "
        "이 숫자가 마이너스면 이익의 질을 의심할 자리입니다.",
    "이자보상배율 1 미만":
        "본업으로 번 돈이 **이자도 못 갚는다**는 뜻입니다. 모자란 만큼은 새로 빌리거나 "
        "무언가를 팔아서 메워야 합니다.",
    "최근 3년 CB·BW 발행":
        "전환사채(CB)·신주인수권부사채(BW)는 나중에 **주식으로 바뀌는 빚**입니다. "
        "은행에서 빌리기 어려울 때 쓰는 통로인 경우가 많고, 주식으로 바뀌면 기존 주주의 "
        "몫이 그만큼 줄어듭니다.",
    "최근 3년 CB·BW 2회 이상":
        "위 조달을 3년 안에 두 번 넘게 했다는 뜻입니다. 한 번은 사정일 수 있지만 "
        "**반복은 구조**에 가깝습니다.",
    "최대주주 변경 최근 3년":
        "회사의 주인이 바뀌었다는 뜻입니다. 정상적인 인수일 수도 있고, 넘긴 쪽이 "
        "손을 뗀 것일 수도 있어 **바뀐 이유를 원문에서 확인해야** 합니다.",
}


def what_it_is(kind: str) -> str:
    return WHAT_IT_IS.get(kind, "")


# 이 리포트를 읽는 순서. 위에서 아래로 읽되 **어디서 멈춰도 되는지**를 같이 적는다.
# 전부 읽어야 쓸 수 있는 문서는 결국 안 읽힌다.
READING_ORDER: tuple[tuple[str, str, str], ...] = (
    ("1", "맨 위 세 줄 · 20초",
     "**몇 개 걸렸나 → 어디로 가고 있나 → 감사인이 뭐라 썼나.** 이 셋이 층이고, "
     "아래로 갈수록 좁혀집니다. 0개 걸림이면 사실상 여기서 끝나도 됩니다 — "
     "0개 걸린 회사의 이후 2년 부실률은 0.00~0.20%로, 상장사 평균(1.5~2.4%)의 "
     "10분의 1도 안 됩니다."),
    ("2", "관리종목 요건까지 몇 칸 · 30초",
     "**여기만 판정선을 우리가 정하지 않았습니다** — 코스닥 상장규정에 숫자가 박혀 "
     "있고 걸리면 관리종목이 됩니다. 다른 층은 우리가 임계를 고르고 검정으로 "
     "정당화했지만 이 층은 그런 논쟁이 없습니다."),
    ("3", "걸린 항목 카드 · 항목당 1분",
     "카드 한 장은 네 줄로 읽습니다. **무엇인지**(첫 줄 설명) → **얼마나 나쁜지**"
     "(상장사·업종 안에서의 위치) → **나아지는 중인지**(3년 추세) → **이 신호가 실제로 "
     "얼마나 맞는지**(실측 부실률)."),
    ("4", "각 카드의 '다만' 줄 · 항목당 10초",
     "걸린 회사의 **대부분은 2년 안에 아무 일도 없었습니다** — 신호마다 93~97%입니다. "
     "이건 유죄 판정이 아니라 여기서 멈추고 이유를 찾아보라는 표시입니다. 이 줄을 "
     "건너뛰면 리포트를 실제보다 세게 읽게 됩니다."),
    ("5", "확인하지 못한 것 · 2분",
     "우리가 **못 읽은 자리**입니다. 걸린 게 하나도 없어도 여기는 봐야 합니다 — "
     "지급보증·특수관계자 거래처럼 숫자표에 안 나오고 주석 본문에만 있는 것들이 "
     "모여 있습니다."),
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
    worsening: bool | None = None    # 이익잉여금 3년 방향. None = 판정 못 함
    audit: str | None = None         # 'adverse'/'concern'/'none'. None = 감사의견 못 받음
    audit_year: str | None = None    # 그 감사의견이 어느 사업연도 것인가
    bad_disclosure: int | None = None  # 최근 3년 불성실공시 지정 횟수. None = 명단 없음

    @property
    def summary(self) -> str:
        known = len(self.fired) + len(self.clear)
        return flag_count_summary(len(self.fired), known)

    @property
    def drift(self) -> str:
        """개수만으로 순서를 매기면 틀린다 — 같은 개수 안에서 방향이 더 크게 가른다.

        `summary` 와 반드시 같이 나가야 한다. 실측으로 3개 걸림 + 악화(8.1%)가
        5개 걸림 + 악화 아님(5.9%)보다 높다.
        """
        return direction_split(len(self.fired), self.worsening)

    @property
    def auditor(self) -> str:
        """감사인이 뭐라고 썼는지. 같은 5개 걸림 안에서 5.2% 와 43.5% 로 가른다.

        표에 안 나오고 문장으로만 있어서 대개 안 읽히는 칸이다 — 부실 상장폐지의
        절반이 넘는 게 감사의견인데도.
        """
        return audit_split(len(self.fired), self.audit, self.audit_year)

    @property
    def disclosure(self) -> str:
        """공시 행태 — 재무제표 밖에서 오는 유일한 층.

        감사 층과 같이 **좁혀준다**. 재무 신호가 없으면 이것만으로는 뜻이 없다
        (핵심 5종 밖 + 불성실공시만 있던 33사 중 부실 0건).
        """
        return disclosure_split(len(self.fired), self.bad_disclosure)


def build(name: str, corp_code: str, fiscal_year: str, flags: list[Flag],
          known: dict[str, bool | None],
          worsening: bool | None = None,
          audit: str | None = None,
          audit_year: str | None = None,
          bad_disclosure: int | None = None) -> Checklist:
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
        worsening=worsening,
        audit=audit,
        audit_year=audit_year,
        bad_disclosure=bad_disclosure,
    )


def evidence_of(flag: Flag) -> tuple[list[str], str]:
    """근거 줄과 검정 상태를 가른다. 검정 상태는 `screen()` 이 마지막 줄에 붙인다."""
    lines = [e for e in flag.evidence if not e.startswith("└")]
    verdict = next((e[1:].strip() for e in flag.evidence if e.startswith("└")),
                   verification_of(flag.kind))
    return lines, verdict
