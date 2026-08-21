"""지배구조 이상 신호 — "사도 되나"에 점수가 아니라 **근거**로 답한다.

왜 점수를 안 내는가:
  "위험도 0.73" 은 아무도 못 믿고 못 반박한다. 이 층은 대신 "무엇이 걸렸고 그게
  어느 엣지에서 나왔는가" 를 낸다. 반박하려면 그 엣지를 반박해야 한다.

왜 재무비율이 아니라 관계인가:
  재무비율로 저평가주를 찾는 건 수십 년간 수만 명이 해왔고 이미 가격에 들어가 있다.
  가격에 잘 안 담기는 건 **지배구조의 이상함**이다 — 순환출자, 상호출자, 공식 계열
  경계를 넘는 연결, 공동 의존점에 물린 위치. 이건 숫자가 아니라 관계라서 개별
  공시를 읽어선 안 보이고, 다 이어야 보인다.

이 모듈은 판단하지 않는다. **걸리는 것을 세고 근거를 붙일 뿐이다.**
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field

MAX_CYCLE_LEN = 6  # 공정거래법상 순환출자 규제도 현실적으로 짧은 고리를 본다
NEAR_HOPS = 2      # 공동 의존점까지 몇 홉이면 '물려 있다' 로 볼 것인가

# 검정 상태를 항목마다 달고 다닌다. 검정 없이 "이상 신호" 라고 부르면 사용자가
# 위험으로 읽는다 — 실제로 검정해보니 셋 중 둘이 반대 방향이었다.
#
# 이 표가 이 도구의 정직성이다. 걸렸다는 것과 위험하다는 것은 다른 말이고,
# 우리는 후자를 아직 대부분 모른다.
VERIFICATION: dict[str, str] = {
    "결손금": (
        "**채택** · 기준시점 4개(2021~2024) × 규모·업종 통제 설정 7개 = 28개 조합 "
        "**전부**에서 유의 (최보수 ×6.35 / ×3.80 / ×2.44 / ×4.10) · 다중검정 보정"
        "(가족 29)에서 **네 시점 전부 Bonferroni 통과** · 관측 창을 365·730·1095일로 "
        "흔들어도 판정이 난 칸은 전부 채택 — 가장 강한 신호다"
    ),
    "당기순손실": (
        "**채택** · 28개 조합 전부에서 유의 (최보수 ×3.21 / ×2.02 / ×2.45 / ×3.37) · "
        "다중검정은 네 시점 전부 FDR 통과 · Bonferroni 는 4개 중 3개 · "
        "관측 창 365·730·1095일 전부에서 뒤집히지 않는다"
    ),
    "영업손실": (
        "**채택(약)** · 28개 조합 전부에서 유의 (최보수 ×2.24 / ×2.83 / ×1.87 / ×2.92) "
        "이지만 다중검정에서 **Bonferroni 를 넘는 시점이 4개 중 2개**(임계 0.00172). "
        "결손금·당기순손실보다 한 단계 약한 근거다. 관측 창을 흔들어도 뒤집히지는 않는다"
    ),
    "공동의존점 근접":
        "검정됨 · 부실과 **반대 방향** (먼 쪽이 2배 · p=0.0007, 감사의견 라벨로도 ×0.50)",
    "순환출자":
        "**미검정** · 보유 1.7% × 부실 1% = 교집합 0.017% 라 표본이 구조적으로 부족",
    "상호 지분 보유":
        "**미검정** · 신호군 부실 10건으로 최소 기준 20건 미달",
    "계열 경계 초과":
        "**미검정** · 공정위 집단명이 DART 에 없어 신호군을 만들 수 없음",
    "대기업집단과의 거리":
        "**채택 안 함** · 감사의견 라벨은 통제하면 ×2.61→×1.29 로 사라진다. 실제 부실 "
        "사건으로 앞을 보면 기준시점 4개에서 ×0.46 → ×0.88 → ×1.70 → ×2.34 로 "
        "**초기 두 시점은 방향이 반대**다. 최근 두 시점에서만 나타나 재현으로 볼 수 없다 — "
        "**가까울수록 감사의견 문제가 적다.** 소속이 위험한 게 아니라 고립이 위험한 쪽",
    "특수관계인 자금거래": "**미검정**",
    "계열사 내부거래": "**미검정**",
}

NOT_A_RISK_NOTE = "부실과 반대 방향(검정: 먼 쪽이 2배, p=0.0007)"


def is_adopted(kind: str) -> bool:
    """검정을 통과해 채택된 검사인가.

    두 가지를 동시에 지켜야 한다. 철회한 검사("**채택 안 함**")가 채택으로 새면
    안 되고, 근거가 한 단계 약한 검사("**채택(약)**")는 채택으로 세야 한다 —
    약한 것과 아닌 것은 다르다. 앞의 것만 막으려고 접두사를 붙이면 뒤가 샌다.
    """
    v = verification_of(kind).lstrip()
    return v.startswith("**채택") and not v.startswith("**채택 안 함")


def verification_of(kind: str) -> str:
    """이 검사가 부실과 연관되는지 확인됐는가. 모르면 모른다고 적는다."""
    return VERIFICATION.get(kind, "**미검정**")

# ⚠️ 임의값이다. 실측에서 이게 없어 사고가 났다 — 삼양사가 태영건설을 **0.06%**
# 보유한 걸 "상호출자" 로 경고했다. 단순투자와 지배목적을 가르는 공식 기준은 없고,
# 참고선은 대량보유 보고 의무 5% · 지분법 적용 20% 다. 1% 는 "무시할 수준은 아님"
# 의 하한으로 잡은 것이며, 근거 블록에 값을 실어 사람이 다시 판단하게 한다.
MIN_MEANINGFUL_PCT = 1.0


# 관측값이 실측 분포의 어디에 있는가. **"좋음/나쁨" 이 아니라 "얼마나 흔치 않은가"** 다.
# 데이터가 지지하는 건 희소성이고, 투자 판단은 사람이 한다.
#
# 실측 기준선(표본 200사·2024): 특수관계인 자금거래는 93.5% 가 0건(p95=2·p99=5),
# 계열사 내부거래는 84.5% 가 0건(p90=3·p95=6·p99=18). 대부분이 0이라 평균은
# 쓸모없고 분위수를 본다.
RARITY_COMMON = "흔함"
RARITY_UNCOMMON = "드묾"
RARITY_RARE = "매우 드묾"


def rarity(value: int, dist: dict[str, float]) -> tuple[str, str]:
    """(등급, 근거 문장). 임의 임계 대신 실측 분포 안의 위치로 말한다.

    종합 점수를 만들지 않는다 — 항목을 하나로 합치는 순간 "위험도 0.73" 이 되고,
    그건 아무도 못 믿고 못 반박한다.
    """
    p95, p99 = dist.get("p95", 0), dist.get("p99", 0)
    zero = dist.get("zero_ratio", 0.0)
    if value > p99:
        grade = RARITY_RARE
        where = f"상위 1% 밖 (p99={p99})"
    elif value > p95:
        grade = RARITY_UNCOMMON
        where = f"상위 1~5% (p95={p95} · p99={p99})"
    else:
        grade = RARITY_COMMON
        where = f"상위 5% 이내 아님 (p95={p95})"
    return grade, f"{value}건 — {where} · 표본의 {zero:.0%}는 0건"



@dataclass(frozen=True)
class Flag:
    """걸린 항목 하나. `evidence` 없이는 만들 수 없다 — 근거 없는 경고는 소음이다."""

    kind: str
    summary: str
    evidence: list[str]

    def __post_init__(self) -> None:
        if not self.evidence:
            raise ValueError(f"근거 없는 신호는 만들 수 없다: {self.kind}")


@dataclass
class Neighborhood:
    """한 종목 주변. 그래프 전체를 들고 다니지 않기 위한 조각."""

    corp_code: str
    out_edges: list[tuple[str, str]] = field(default_factory=list)  # (target, type)
    in_edges: list[tuple[str, str]] = field(default_factory=list)   # (source, type)


def _adjacency(edges: list[tuple[str, str, str]]) -> dict[str, set[str]]:
    adj: dict[str, set[str]] = defaultdict(set)
    for a, b, _ in edges:
        adj[a].add(b)
    return adj


def neighborhood(edges: list[tuple[str, str, str]], corp_code: str) -> Neighborhood:
    n = Neighborhood(corp_code=corp_code)
    for a, b, t in edges:
        if a == corp_code:
            n.out_edges.append((b, t))
        if b == corp_code:
            n.in_edges.append((a, t))
    return n


def mutual_holdings(
    edges: list[tuple[str, str, str]],
    corp_code: str,
    *,
    name=str,
    share_of: dict[tuple[str, str], float] | None = None,
    min_pct: float = MIN_MEANINGFUL_PCT,
    dist: dict[str, float] | None = None,
) -> Flag | None:
    """서로 지분을 보유 — A가 B를, B가 A를 함께 보유.

    **`상호출자` 라고 부르지 않는다.** 그건 상호출자제한기업집단의 계열회사 간에
    적용되는 규제 용어인데, 여기서 잡히는 건 단순 지분 보유까지 포함한다.
    실측에서 0.06% 보유를 "상호출자" 로 경고한 사고가 있었다 — 이름을 잘못 붙이면
    없는 규제 위반을 있는 것처럼 읽힌다.

    `share_of` 를 주면 임계 미만을 걸러낸다. 안 주면 거르지 않되 근거에
    **'지분율 미상'** 을 붙여, 사람이 그 사실을 알고 판단하게 한다.
    """
    outs = {b for a, b, _ in edges if a == corp_code}
    ins = {a for a, b, _ in edges if b == corp_code}
    lines = []
    for c in sorted(outs & ins):
        pcts = [p for p in ((share_of or {}).get((corp_code, c)),
                            (share_of or {}).get((c, corp_code))) if p is not None]
        if share_of is None or not pcts:
            lines.append(f"{name(corp_code)} ↔ {name(c)} · 지분율 미상")
        elif max(pcts) >= min_pct:
            lines.append(f"{name(corp_code)} ↔ {name(c)} · 최대 {max(pcts):.2f}%")
    if not lines:
        return None
    head = "서로 보유하는 상대 {}곳 (규제상 상호출자와는 별개)".format(len(lines))
    if dist:
        grade, why = rarity(len(lines), dist)
        head = f"{grade} — {why} · 규제상 상호출자와는 별개"
    return Flag(kind="상호 지분 보유", summary=head, evidence=lines)


def circular_holdings(
    edges: list[tuple[str, str, str]],
    corp_code: str,
    *,
    name=str,
    max_len: int = MAX_CYCLE_LEN,
    dist: dict[str, float] | None = None,
) -> Flag | None:
    """순환출자 — A→B→C→…→A 로 돌아오는 고리.

    상호출자(길이 2)는 따로 세므로 여기서는 **길이 3 이상**만 본다. 둘을 합치면
    "무엇이 걸렸는지" 가 뭉개진다.
    """
    adj = _adjacency(edges)
    cycles: list[list[str]] = []
    seen: set[tuple[str, ...]] = set()

    queue: deque[list[str]] = deque([[corp_code]])
    while queue:
        path = queue.popleft()
        if len(path) > max_len:
            continue
        for nxt in adj.get(path[-1], ()):
            if nxt == corp_code and len(path) >= 3:
                key = tuple(sorted(path))
                if key not in seen:
                    seen.add(key)
                    cycles.append([*path, corp_code])
            elif nxt not in path:
                queue.append([*path, nxt])

    if not cycles:
        return None
    cycles.sort(key=len)
    head = f"고리 {len(cycles)}건 (최단 {len(cycles[0]) - 1}단계)"
    if dist:
        grade, why = rarity(len(cycles), dist)
        head = f"{grade} — {why} · 최단 {len(cycles[0]) - 1}단계"
    return Flag(
        kind="순환출자", summary=head,
        evidence=[" → ".join(name(c) for c in cyc) for cyc in cycles[:5]],
    )


def hops_to(
    edges: list[tuple[str, str, str]], start: str, targets: set[str], *, max_hops: int
) -> dict[str, int]:
    """무방향 홉수. 출자 방향과 무관하게 '얽혀 있는가' 를 본다 — 위험은 방향을 안 가린다."""
    und: dict[str, set[str]] = defaultdict(set)
    for a, b, _ in edges:
        und[a].add(b)
        und[b].add(a)

    dist = {start: 0}
    queue = deque([start])
    found: dict[str, int] = {}
    while queue:
        cur = queue.popleft()
        if dist[cur] >= max_hops:
            continue
        for nxt in und.get(cur, ()):
            if nxt in dist:
                continue
            dist[nxt] = dist[cur] + 1
            if nxt in targets:
                found[nxt] = dist[nxt]
            queue.append(nxt)
    return found


def near_chokepoint(
    edges: list[tuple[str, str, str]],
    corp_code: str,
    chokepoints: dict[str, int],
    *,
    name=str,
    max_hops: int = NEAR_HOPS,
    dist: dict[str, float] | None = None,
) -> Flag | None:
    """공동 의존점에 물려 있는가. **위험 신호가 아니다** — 검정으로 확인했다.

    신호 검정(2022-06 기준 · 라벨 1,000일 창): 공동의존점에서 **먼** 회사가 가까운
    회사보다 부실률이 2배였다(1.9% vs 0.9% · p=0.0007). 세 시점 모두 같은 방향이다.
    허브 근처에 있다는 건 대기업 계열이라는 뜻이기도 해서, 규모 교란일 가능성이 크다.
    그래서 인과가 아니라 **연관까지만** 말한다.

    그럼 왜 남겨두나: "이 회사가 어디에 물려 있는가" 는 구조적으로 유용한 정보다.
    다만 **경고로 읽히면 안 되므로** 요약에 그 사실을 붙인다.

    `chokepoints` 는 {corp_code: 매개중심성 순위}. 차수는 낮은데 매개가 높은 노드는
    서로 무관해 보이는 집단들이 공동으로 붙어 있는 지점이라, 거기가 막히면 동시에
    영향을 받는다. 실측: 건설공제조합은 차수 15인데 매개중심성 3위였다.
    """
    hit = hops_to(edges, corp_code, set(chokepoints), max_hops=max_hops)
    hit.pop(corp_code, None)
    if not hit:
        return None
    ordered = sorted(hit.items(), key=lambda kv: (kv[1], chokepoints[kv[0]]))
    head = f"{max_hops}홉 안에 공동 의존점 {len(hit)}곳"
    if dist:
        grade, why = rarity(len(hit), dist)
        head = f"{grade} — {why} · {max_hops}홉 기준"
    head += " · " + NOT_A_RISK_NOTE
    return Flag(
        kind="공동의존점 근접",
        summary=head,
        evidence=[
            f"{name(c)} — {h}홉 · 매개중심성 {chokepoints[c]}위" for c, h in ordered[:5]
        ],
    )


def crosses_group_boundary(
    edges: list[tuple[str, str, str]],
    corp_code: str,
    group_of: dict[str, str],
    *,
    name=str,
) -> Flag | None:
    """공식 계열 경계를 넘는 출자.

    `group_of` 는 {corp_code: 공식 기업집단명}. 지금은 호출부가 넣어주는 사전이고,
    제대로 하려면 공정거래위원회 기업집단포털을 붙여야 한다 — DART 에는 없는 데이터다.
    라벨이 없는 노드는 판정하지 않는다(모르는 걸 '넘었다' 로 세지 않는다).
    """
    mine = group_of.get(corp_code)
    if not mine:
        return None
    crossing = []
    for a, b, _ in edges:
        for src, dst in ((a, b), (b, a)):
            if src != corp_code:
                continue
            other = group_of.get(dst)
            if other and other != mine:
                crossing.append((dst, other))
    if not crossing:
        return None
    uniq = sorted(set(crossing))
    return Flag(
        kind="계열 경계 초과",
        summary=f"공식 집단 '{mine}' 밖으로 이어진 상대 {len(uniq)}곳",
        evidence=[f"{name(c)} ({g})" for c, g in uniq[:5]],
    )


def conglomerate_distance(
    edges: list[tuple[str, str, str]],
    corp_code: str,
    members: set[str],
    *,
    name=str,
) -> Flag | None:
    """대기업집단과의 거리 — 소속 / 연결 / 고립.

    관측(그래프 안 상장사 2,255사 · 감사의견 라벨):
      통제 전   소속 1.6% → 미소속·연결 3.5% → 미소속·고립 6.8%   (×2.61)

    **가까울수록 문제가 적다.** 걸리는 건 '소속' 이 아니라 **'고립'** 이다 —
    이름을 반대로 읽지 않도록 이 방향을 요약에 싣는다.

    다만 **이 배율은 결론이 아니다.** 고립군은 작은 회사와 특정 업종에 몰려 있고
    둘 다 원래 문제가 많은 쪽이다. 자산총계와 표준산업분류로 통제해보면:

      자산 2층 × 업종 1자리   ×1.84 · p=0.005
      자산 4층 × 업종 1자리   ×1.52 · p=0.050
      자산 4층 × 업종 2자리   ×1.29 · p=0.157   ← 가장 보수적

    통제를 촘촘히 할수록 배율이 계속 줄고 유의성이 사라진다. 유의해지는 설정을 골라
    쓰는 건 파라미터 고르기다 — 층1에서 모듈러리티를 반려한 것과 같은 이유로
    **채택하지 않는다.**

    라벨을 바꿔 앞을 보면 더 나쁘다. 감사의견은 이미 드러난 문제라, 기준시점 T 의
    구조로 T 이후 730일의 실제 부실(부도·회생·관리절차·영업정지)을 맞히는지 봤다:

      T=2022-06-30   고립 2.45% vs 나머지 2.78%   ×0.88   (오히려 반대)
      T=2023-06-30   고립 3.14% vs 나머지 1.92%   ×1.70   (통제 후 최보수)

    **기준시점 하나 바꿨더니 방향이 뒤집힌다.** 크기는커녕 방향도 말할 수 없다.
    그래서 이 검사는 걸린 사실과 실측 비율만 내고, 예측이라고 말하지 않는다.

    `members` 가 비면 판정하지 않는다. 모르는 걸 '고립' 으로 세면 거의 모든 회사가 걸린다.
    """
    if not members:
        return None
    if corp_code in members:
        return None                      # 소속은 가장 안전한 쪽 — 경고하지 않는다
    neighbours = {b for a, b, _ in edges if a == corp_code}
    neighbours |= {a for a, b, _ in edges if b == corp_code}
    linked = sorted(neighbours & members)
    if linked:
        return Flag(
            kind="대기업집단과의 거리",
            summary=f"미소속이지만 소속사 {len(linked)}곳과 연결 (실측 문제율 3.5%)",
            evidence=[name(c) for c in linked[:5]],
        )
    return Flag(
        kind="대기업집단과의 거리",
        summary="고립 — 대기업집단과 지분 연결 없음 "
                "(실측 문제율 6.8% · 다만 규모·업종을 맞추면 차이가 사라진다)",
        evidence=[f"{name(corp_code)} 의 지분 상대 {len(neighbours)}곳 중 대기업집단 소속 0곳"],
    )


def accumulated_deficit(retained: float | None, *, year: str = "") -> Flag | None:
    """결손금 — 누적 이익잉여금이 마이너스.

    **가장 강한 신호다.** 지분 구조 검사 7종은 교란을 통제하면 전부 사라지는데,
    이건 기준시점을 바꾸고 통제를 촘촘히 해도 남는다:

      T=2021-06-30 · 2020년 재무   해당 503사 · 이후 2년 부실 7.16%   ×6.35 · p=0.0001
      T=2022-06-30 · 2021년 재무   해당 579사 · 이후 2년 부실 6.04%   ×3.80 · p=0.0001
      T=2023-06-30 · 2022년 재무   해당 583사 · 이후 2년 부실 6.00%   ×2.44 · p=0.0002
      T=2024-06-30 · 2023년 재무   해당 595사 · 이후 2년 부실 7.06%   ×4.10 · p=0.0001

    두 시점 모두 규모(자산총계) × 업종 통제 설정 7개 **전부**에서 유의했다. 구조
    신호가 떨어진 게 잣대가 빡세서가 아니라는 뜻이기도 하다 — 같은 잣대를 통과한다.

    **배율을 "망한다" 로 읽으면 안 된다.** 기저율이 2.6~3.1% 라 배율을 곱해도 5~7% 다
    — 걸린 기업의 93~95%는 2년 안에 아무 일도 없었다. 상장사의 26%가 여기 걸리고
    실제 부실의 48~67%를 잡는다. `signal/usefulness.py` 가 이 숫자를 낸다.

    `retained` 가 None 이면 판정하지 않는다. 재무를 못 받은 걸 '흑자' 로 세지 않는다.
    """
    if retained is None or retained >= 0:
        return None
    label = f"{year}년 " if year else ""
    return Flag(
        kind="결손금",
        summary=f"{label}이익잉여금이 마이너스 — 누적 결손 "
                f"{abs(retained) / 1e8:,.0f}억",
        evidence=["결손 기업의 이후 2년 부실률 실측 6.0~7.2% "
                  "(전체 2.8~3.3% · 규모·업종 통제 후 ×2.4~6.4 · 기준시점 4개)",
                  "다만 **결손 기업의 93~94%는 2년 안에 아무 일도 없었다** — "
                  "상장사의 26%가 여기 걸리고, 실제 부실의 47~67%를 잡는다"],
    )


def operating_loss(op_income: float | None, *, year: str = "") -> Flag | None:
    """영업손실 — 본업에서 돈을 못 벌었다.

    결손금 다음으로 강한 신호이고, 역시 두 기준시점 × 통제 설정 7개 전부에서 유의했다:

      T=2021-06-30   해당 580사 · 5.00%   ×2.24 · p=0.0024
      T=2022-06-30   해당 574사 · 6.10%   ×2.83 · p=0.0006
      T=2023-06-30   해당 592사 · 5.41%   ×1.87 · p=0.0080
      T=2024-06-30   해당 749사 · 5.87%   ×2.92 · p=0.0001

    결손금과 겹치지만 같지는 않다 — 결손금은 **누적**이고 이건 **당해**다. 오래
    벌어둔 회사가 한 해 적자를 낸 경우는 영업손실만 걸린다.

    **결손금보다 한 단계 약한 근거다.** 판정이 나온 검정 14개를 한 가족으로 묶어
    보정하면 결손금은 Bonferroni(임계 0.00357)까지 넘지만 이건 FDR 만 넘는다.
    `signal/multiplicity.py` 와 `scripts/adjust_multiplicity.py` 참조.
    """
    if op_income is None or op_income >= 0:
        return None
    label = f"{year}년 " if year else ""
    return Flag(
        kind="영업손실",
        summary=f"{label}영업이익이 마이너스 — 영업손실 {abs(op_income) / 1e8:,.0f}억",
        evidence=["영업손실 기업의 이후 2년 부실률 실측 5.1~6.2% "
                  "(전체 2.8~3.3% · 규모·업종 통제 후 ×1.9~2.9 · 기준시점 4개)",
                  "다만 **영업손실 기업의 94~95%는 2년 안에 아무 일도 없었다** — "
                  "상장사의 26~33%가 여기 걸리고, 실제 부실의 43~60%를 잡는다"],
    )


def net_loss(net_income: float | None, *, year: str = "") -> Flag | None:
    """당기순손실 — 영업외까지 합쳐 최종적으로 손실.

    기준시점 3개 × 통제 설정 7개 전부에서 유의했다:

      T=2021-06-30   해당 733사 · 5.05%   ×3.21 · p=0.0005
      T=2022-06-30   해당 651사 · 5.07%   ×2.02 · p=0.0052
      T=2023-06-30   해당 716사 · 5.59%   ×2.45 · p=0.0006
      T=2024-06-30   해당 815사 · 5.89%   ×3.37 · p=0.0001

    **한때 '시점에 따라 갈린다' 며 뺐던 신호다.** 그 판정이 틀렸다 — 당시 재무 검정이
    표본을 '지분 그래프에 있는 회사' 로 좁혀놨는데, DART 타법인출자 API 가 옛 사업연도를
    거의 안 줘서(2020년은 2021년의 3분의 1) 표본이 인위적으로 얇았다. 재무 신호에
    그래프 소속을 요구할 이유가 없어 그 조건을 빼자 세 시점 전부에서 재현됐다.

    셋 중 가장 넓게 걸린다(상장사의 30~36%). 재현율은 가장 높고(49~69%) 정밀도는
    가장 낮다 — 넓게 거는 신호의 전형이다.
    """
    if net_income is None or net_income >= 0:
        return None
    label = f"{year}년 " if year else ""
    return Flag(
        kind="당기순손실",
        summary=f"{label}당기순이익이 마이너스 — 순손실 {abs(net_income) / 1e8:,.0f}억",
        evidence=["순손실 기업의 이후 2년 부실률 실측 5.1~5.9% "
                  "(전체 2.8~3.3% · 규모·업종 통제 후 ×2.0~3.4 · 기준시점 4개)",
                  "다만 **순손실 기업의 94~95%는 2년 안에 아무 일도 없었다** — "
                  "상장사의 30~36%가 여기 걸리고, 실제 부실의 49~69%를 잡는다"],
    )


def screen(
    edges: list[tuple[str, str, str]],
    corp_code: str,
    *,
    name=str,
    chokepoints: dict[str, int] | None = None,
    group_of: dict[str, str] | None = None,
    share_of: dict[tuple[str, str], float] | None = None,
    baseline: dict[str, dict[str, float]] | None = None,
    conglomerate_members: set[str] | None = None,
    retained_earnings: float | None = None,
    operating_income: float | None = None,
    net_income: float | None = None,
    fiscal_year: str = "",
) -> list[Flag]:
    """걸리는 것만 모아서 돌려준다. 빈 목록은 '이상 없음' 이 아니라 **'이 검사들에는
    안 걸렸음'** 이다 — 검사 범위 밖의 위험은 이 함수가 모른다."""
    b = baseline or {}
    found = [
        mutual_holdings(edges, corp_code, name=name, share_of=share_of,
                        dist=b.get("mutual")),
        circular_holdings(edges, corp_code, name=name, dist=b.get("cycles")),
        near_chokepoint(edges, corp_code, chokepoints or {}, name=name,
                        dist=b.get("near_chokepoint")),
        crosses_group_boundary(edges, corp_code, group_of or {}, name=name),
        conglomerate_distance(edges, corp_code, conglomerate_members or set(),
                              name=name),
        accumulated_deficit(retained_earnings, year=fiscal_year),
        operating_loss(operating_income, year=fiscal_year),
        net_loss(net_income, year=fiscal_year),
    ]
    out: list[Flag] = []
    for f in found:
        if f is None:
            continue
        # 검정 상태를 붙여 내보낸다 — 걸렸다는 것과 위험하다는 것은 다른 말이다.
        out.append(Flag(kind=f.kind,
                        summary=f.summary,
                        evidence=[*f.evidence, f"└ {verification_of(f.kind)}"]))
    return out


# 공정위 공시(pblntf_ty=J)에서 오는 신호. 본문을 안 읽어도 **공시 종류와 건수**만으로
# 의미가 있다 — "이 회사는 작년에 특수관계인 자금차입을 6번 공시했다" 는 그 자체로
# 사실이고 반박하려면 그 공시를 반박해야 한다.
FUNDING_KEYWORDS = ("자금차입", "자금대여", "자금거래", "채무보증", "담보제공")
TRADE_KEYWORDS = ("상품ㆍ용역거래", "상품·용역거래", "내부거래")


def related_party_funding(
    reports: list[tuple[str, str]], *, min_count: int = 1
) -> Flag | None:
    """특수관계인과의 자금거래 — 차입·대여·보증·담보.

    `reports` 는 `(공시일, 보고서명)` 목록. 지분 관계가 정상으로 보여도 자금이
    특수관계인 쪽으로 오가면 얘기가 다르다. 실측(2024 1분기 표본 300건):
    특수관계인 자금차입 25건 · 자금대여 8건.
    """
    hits = [(d, n) for d, n in reports if any(k in n for k in FUNDING_KEYWORDS)]
    if len(hits) < min_count:
        return None
    return Flag(
        kind="특수관계인 자금거래",
        summary=f"자금 차입·대여·보증 공시 {len(hits)}건",
        evidence=[f"{d} {n}" for d, n in sorted(hits, reverse=True)[:5]],
    )


def internal_trade(reports: list[tuple[str, str]], *, min_count: int = 3) -> Flag | None:
    """계열사 간 상품·용역거래.

    한두 건은 정상 영업이라 `min_count` 를 3으로 둔다 — **임의값이고**, 업종에 따라
    적정선이 다르다. 건수를 근거에 실어 사람이 다시 판단하게 한다.
    """
    hits = [(d, n) for d, n in reports if any(k in n for k in TRADE_KEYWORDS)]
    if len(hits) < min_count:
        return None
    return Flag(
        kind="계열사 내부거래",
        summary=f"상품·용역거래 공시 {len(hits)}건 (임계 {min_count}건)",
        evidence=[f"{d} {n}" for d, n in sorted(hits, reverse=True)[:5]],
    )


def _counted_flag(
    reports: list[tuple[str, str]],
    keywords: tuple[str, ...],
    kind: str,
    dist: dict[str, float] | None,
    min_count: int,
) -> Flag | None:
    hits = [(d, n) for d, n in reports if any(k in n for k in keywords)]
    if not hits or len(hits) < min_count:
        return None
    if dist:
        grade, why = rarity(len(hits), dist)
        summary = f"{grade} — {why}"
    else:
        summary = f"공시 {len(hits)}건 (기준선 없음 — 흔한 수준인지 알 수 없음)"
    return Flag(
        kind=kind,
        summary=summary,
        evidence=[f"{d} {n}" for d, n in sorted(hits, reverse=True)[:5]],
    )


def funding_rarity(
    reports: list[tuple[str, str]], dist: dict[str, float] | None = None
) -> Flag | None:
    """특수관계인 자금거래를 실측 분포 위에 놓는다."""
    return _counted_flag(reports, FUNDING_KEYWORDS, "특수관계인 자금거래", dist, 1)


def trade_rarity(
    reports: list[tuple[str, str]], dist: dict[str, float] | None = None
) -> Flag | None:
    """계열사 내부거래를 실측 분포 위에 놓는다."""
    return _counted_flag(reports, TRADE_KEYWORDS, "계열사 내부거래", dist, 1)
