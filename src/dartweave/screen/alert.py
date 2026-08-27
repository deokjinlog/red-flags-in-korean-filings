"""경고 한 건. **판정이 아니라 관측 + 실측 기저율 + 원문 위치**다.

"이 회사 위험합니다" 는 우리가 할 말이 아니다. 우리가 할 수 있는 말은 이것뿐이다 —
**무엇이 떴고, 그게 어디에 적혀 있고, 같은 게 떴던 회사들이 실제로 어떻게 됐는가.**

각 신호에 붙은 숫자는 교과서 기준선이 아니라 상장사 전수에서 직접 잰 값이고,
`Evidence` 가 그 출처(기준시점·표본·측정일)를 같이 들고 다닌다. 숫자만 떼어
옮기면 언제 잰 건지 잃어버려서, 낡은 값을 새 값처럼 쓰게 된다.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Evidence:
    """이 신호가 붙었던 회사들이 실제로 어떻게 됐는가."""

    hit: int                  # 신호가 걸린 회사 수
    distressed: int           # 그중 관측 창 안에 부실이 난 수
    base_rate: float          # 같은 표본의 전체 부실률 (%)
    sample: int               # 표본 크기
    as_of: str                # 기준시점
    window_days: int = 730
    lead_median_days: int | None = None   # 신호 → 첫 부실까지 (중앙값)
    lead_min_days: int | None = None
    bases: int = 1            # 몇 개 기준시점에서 확인했나

    @property
    def rate(self) -> float:
        return self.distressed / self.hit * 100 if self.hit else 0.0

    @property
    def ratio(self) -> float:
        return self.rate / self.base_rate if self.base_rate else 0.0

    @property
    def survived(self) -> float:
        """걸리고도 아무 일 없었던 비율. **이 줄을 빼면 경고가 과장된다.**"""
        return 100.0 - self.rate

    def sentence(self) -> str:
        years = self.window_days // 365
        s = (f"같은 신호가 걸렸던 {self.hit}사 중 {self.distressed}사가 "
             f"이후 {years}년 안에 부실로 갔습니다 — **{self.rate:.1f}%**, "
             f"전체 평균 {self.base_rate:.1f}%의 {self.ratio:.1f}배.")
        if self.lead_median_days:
            s += (f" 신호가 뜬 뒤 실제 사건까지 중앙값 "
                  f"{self.lead_median_days // 30}개월")
            if self.lead_min_days:
                s += f", 가장 빨랐던 경우도 {self.lead_min_days}일"
            s += " 걸렸습니다."
        return s

    def caveat(self) -> str:
        return (f"그래도 **{self.survived:.0f}%는 아무 일도 없었습니다.** "
                f"이건 판정이 아니라 원문을 열어 볼 자리입니다.")

    def provenance(self) -> str:
        note = f"기준시점 {self.as_of} · 표본 {self.sample:,}사"
        note += (f" · 기준시점 {self.bases}개에서 확인"
                 if self.bases > 1 else " · **기준시점 1개** — 아직 흔들어보지 않았습니다")
        return note


@dataclass(frozen=True)
class Alert:
    kind: str                 # 신호 이름
    what: str                 # 이게 무슨 뜻인가 (한 줄)
    found: str                # 이 회사에서 무엇이 발견됐나
    where: str                # DART 어디에 적혀 있나
    evidence: Evidence
    rcept_no: str | None = None      # 근거가 된 공시 접수번호
    refutes: str = ""                # 무엇이 사실이면 이 경고가 풀리는가

    @property
    def url(self) -> str | None:
        """원문 바로가기. 접수번호가 없으면 링크를 지어내지 않는다."""
        if not self.rcept_no:
            return None
        return f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={self.rcept_no}"


# 우리가 아예 보지 않는 것. 경고에 **매번** 따라붙어야 한다.
#
# 2026-07 시행된 강화 요건의 핵심(시가총액 200억·주가 1,000원 미만)이 전부 주가
# 기반인데 DART 에는 주가가 없다. 2026-08 신규 관리종목 36곳이 전부 그 사유였다.
# 이걸 안 밝히면 "경고 없음" 을 안전으로 읽는다.
BLIND_SPOTS: tuple[str, ...] = (
    "주가·시가총액 요건 — DART 에 주가가 없습니다. 2026-07 강화된 시총 200억·"
    "동전주(1,000원 미만) 기준은 여기서 판정하지 않습니다",
    "부실 사건의 33%는 결손금도 감사 경고도 없이 일어났습니다 — "
    "경고가 없다는 건 안전하다는 뜻이 아닙니다",
    "밸류에이션·사업 전망·경영진 — 숫자표 밖에 있는 것은 보지 않습니다",
)


# 실측 근거 한 벌. **숫자를 여기 말고 다른 데 적지 않는다.**
# 리포트와 경고가 각자 숫자를 들고 있으면 한쪽만 갱신돼서 조용히 갈라진다 —
# `check_company` 와 `ask` 가 실제로 그렇게 갈라진 적이 있다.
MEASURED: dict[str, Evidence] = {
    "의견거절·한정": Evidence(hit=43, distressed=17, base_rate=3.94, sample=2333,
                        as_of="20240630", lead_median_days=486, lead_min_days=92),
    "계속기업 경고": Evidence(hit=44, distressed=14, base_rate=3.94, sample=2333,
                       as_of="20240630", lead_median_days=486, lead_min_days=92),
    "적정인데 계속기업 경고": Evidence(hit=37, distressed=10, base_rate=3.94, sample=2333,
                            as_of="20240630", lead_median_days=486, lead_min_days=92),
    "결손금": Evidence(hit=633, distressed=59, base_rate=3.94, sample=2333,
                    as_of="20240630", lead_median_days=508, lead_min_days=92, bases=4),
}

WHAT: dict[str, str] = {
    "의견거절·한정":
        "감사인이 **적정 의견을 주지 않았다**는 뜻입니다. 장부를 확인할 수 없었거나, "
        "확인해 보니 기준에 안 맞았다는 겁니다. 코스닥 규정상 의견거절은 그 자체로 "
        "상장폐지 사유라, 이건 예고라기보다 이미 벌어진 일에 가깝습니다.",
    "계속기업 경고":
        "감사인이 **이 회사가 계속 존속할 수 있을지 의심스럽다**고 감사보고서에 "
        "적어 넣은 것입니다. 의견 자체는 적정일 수 있는데, 그 뒤에 경고 문단이 "
        "따로 붙습니다. 표에는 안 나오고 문장으로만 있어서 대개 안 읽힙니다.",
    "적정인데 계속기업 경고":
        "의견은 **적정**인데 감사인이 계속기업 경고만 따로 단 경우입니다. "
        "숫자표로는 정상으로 보이는 회사가 여기 섞여 있어서, 재무만 봐서는 안 보입니다.",
    "결손금":
        "회사를 세운 뒤로 번 돈과 잃은 돈을 전부 합쳤더니 마이너스라는 뜻입니다. "
        "한 해 실적이 아니라 **누적**이라, 쌓아 둔 완충이 없다는 뜻이기도 합니다.",
}

WHERE: dict[str, str] = {
    "의견거절·한정": "정기보고서 → V. 회계감사인의 감사의견 등 → 1. 외부감사에 관한 사항",
    "계속기업 경고": "같은 곳 — 감사의견 오른쪽 **강조사항** 칸",
    "적정인데 계속기업 경고": "같은 곳 — 의견은 적정, 강조사항 칸에 계속기업",
    "결손금": "정기보고서 → III. 재무에 관한 사항 → 연결 재무상태표 → 이익잉여금(결손금)",
}

REFUTES: dict[str, str] = {
    "의견거절·한정": "다음 사업연도 감사보고서에 적정의견이 나오면 풀립니다",
    "계속기업 경고": "다음 감사보고서에서 강조사항이 빠지면 풀립니다",
    "적정인데 계속기업 경고": "다음 감사보고서에서 강조사항이 빠지면 풀립니다",
    "결손금": "이익잉여금이 다시 플러스로 돌아서면 풀립니다",
}


def build(kind: str, found: str, *, rcept_no: str | None = None) -> Alert | None:
    """실측 근거가 없는 신호로는 경고를 만들지 않는다."""
    ev = MEASURED.get(kind)
    if ev is None:
        return None
    return Alert(kind=kind, what=WHAT.get(kind, ""), found=found,
                 where=WHERE.get(kind, ""), evidence=ev,
                 rcept_no=rcept_no, refutes=REFUTES.get(kind, ""))
