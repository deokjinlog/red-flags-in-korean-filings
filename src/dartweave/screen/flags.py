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
    # ⚠️ 아래 값은 답안지에서 **영업정지를 뺀 뒤** 다시 잰 것이다. 하나은행(532조)·
    #    신한은행 같은 대기업 제재가 부실로 세어지고 있었고, 그 회사들은 어느 신호에도
    #    안 걸려서 비교군 쪽 사고율을 올려 배율을 깎고 있었다. 대신 라벨이 810→526건으로
    #    줄어 앞 기준시점(2021·2022)은 검정력이 사라졌다 — 그래서 4개가 아니라 2개다.
    "이자보상배율 1 미만": (
        "**채택** · 기준시점 2개(2023·2024) × 규모·업종 통제 7설정 = 14개 조합 "
        "**전부**에서 유의 (최보수 ×5.32 / ×12.36 · p 전부 0.0005) · "
        "해당 713~901사 · 실측 부실률 3.6~5.4%"
    ),
    "영업현금흐름 음수": (
        "**채택** · 14개 조합 **전부**에서 유의 (최보수 ×3.88 / ×7.33 · p 전부 0.0005) · "
        "해당 764~809사 · 실측 부실률 3.1~6.0%"
    ),
    "결손금": (
        "**채택** · 14개 조합 **전부**에서 유의 (최보수 ×6.65 / ×9.47 · p 전부 0.0005) · "
        "해당 618~633사 · 실측 부실률 4.2~7.4% · 두 시점 전부 Bonferroni 통과"
    ),
    "당기순손실": (
        "**채택** · 14개 조합 **전부**에서 유의 (최보수 ×5.94 / ×11.71 · p 전부 0.0005) · "
        "해당 752~853사 · 실측 부실률 3.7~5.7%"
    ),
    "영업손실": (
        "**채택** · 14개 조합 **전부**에서 유의 (최보수 ×5.46 / ×8.30 · p 전부 0.0005) · "
        "해당 624~778사 · 실측 부실률 4.0~5.9%"
    ),
    "이익잉여금 3년 악화": (
        "**채택** · 14개 조합 **전부**에서 유의 (최보수 ×4.55 / ×13.38 · p 전부 0.0005) · "
        "해당 460~568사 · 실측 부실률 4.6~8.5% · **같은 개수 안에서 가장 크게 가른다** — "
        "4개 걸림 + 악화 127사 7.1% 대 악화 아님 83사 0.0%"
    ),
    "영업이익 3년 악화": (
        "**채택 안 함** · 두 시점 중 하나만 판정이 났고(2024, 최보수 ×1.79) 다른 시점은 "
        "표본 부족. 원판정으로도 약하다 — 영업손실 걸린 회사 안에서 방향으로 갈라보면 "
        "**개선 쪽이 오히려 높다**(개선 7.8% > 악화 6.3%). 바닥에서 조금 올라온 것도 "
        "개선으로 잡히기 때문이다. 이익잉여금 방향과 **반드시 따로** 둔다"
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
        "사건으로 앞을 보면 기준시점 4개에서 ×0.45 → ×0.83 → ×1.46 → ×1.77 로 "
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

      T=2021-06-30 · 2020년 재무   해당 503사 · 이후 2년 부실 7.75%   ×6.78 · p=0.0001
      T=2022-06-30 · 2021년 재무   해당 579사 · 이후 2년 부실 6.74%   ×4.16 · p=0.0001
      T=2023-06-30 · 2022년 재무   해당 583사 · 이후 2년 부실 7.03%   ×2.69 · p=0.0001
      T=2024-06-30 · 2023년 재무   해당 595사 · 이후 2년 부실 9.58%   ×4.53 · p=0.0001

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
        evidence=["결손 기업의 이후 2년 부실률 실측 4.2~7.4% "
                  "(전체 1.5~2.4% · 규모·업종 통제 후 ×6.7~9.5 · 기준시점 2개)",
                  "다만 **결손 기업의 93~96%는 2년 안에 아무 일도 "
                  "없었다** — 상장사의 27%가 여기 걸리고, 실제 부실의 "
                  "76~85%를 잡는다"],
    )


def operating_loss(op_income: float | None, *, year: str = "") -> Flag | None:
    """영업손실 — 본업에서 돈을 못 벌었다.

    결손금 다음으로 강한 신호이고, 역시 두 기준시점 × 통제 설정 7개 전부에서 유의했다:

      T=2021-06-30   해당 580사 · 5.52%   ×2.44 · p=0.0010
      T=2022-06-30   해당 574사 · 6.62%   ×2.96 · p=0.0004
      T=2023-06-30   해당 592사 · 6.25%   ×1.96 · p=0.0030
      T=2024-06-30   해당 749사 · 7.74%   ×3.13 · p=0.0001

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
        evidence=["영업손실 기업의 이후 2년 부실률 실측 4.0~5.9% "
                  "(전체 1.5~2.4% · 규모·업종 통제 후 ×5.5~8.3 · 기준시점 2개)",
                  "다만 **영업손실 기업의 94~96%는 2년 안에 아무 일도 "
                  "없었다** — 상장사의 27~33%가 여기 걸리고, 실제 부실의 "
                  "74~84%를 잡는다"],
    )


def net_loss(net_income: float | None, *, year: str = "") -> Flag | None:
    """당기순손실 — 영업외까지 합쳐 최종적으로 손실.

    기준시점 3개 × 통제 설정 7개 전부에서 유의했다:

      T=2021-06-30   해당 733사 · 5.46%   ×3.41 · p=0.0002
      T=2022-06-30   해당 651사 · 5.53%   ×2.27 · p=0.0016
      T=2023-06-30   해당 716사 · 6.42%   ×2.43 · p=0.0002
      T=2024-06-30   해당 815사 · 7.85%   ×4.03 · p=0.0001

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
        evidence=["당기순손실 기업의 이후 2년 부실률 실측 3.7~5.7% "
                  "(전체 1.5~2.4% · 규모·업종 통제 후 ×5.9~11.7 · 기준시점 2개)",
                  "다만 **당기순손실 기업의 94~96%는 2년 안에 아무 일도 "
                  "없었다** — 상장사의 33~37%가 여기 걸리고, 실제 부실의 "
                  "82~89%를 잡는다"],
    )


def negative_operating_cashflow(cash: float | None, *, year: str = "") -> Flag | None:
    """영업활동현금흐름 음수 — 본업에서 현금이 나가고 있다.

    기준시점 4개 × 통제 설정 7개 전부에서 유의했다:

      T=2021   해당 453사 · 이후 2년 부실 5.96%   ×2.01 · p=0.0082
      T=2022   해당 754사 · 5.31%                ×2.16 · p=0.0011
      T=2023   해당 776사 · 5.80%                ×1.96 · p=0.0046
      T=2024   해당 726사 · 8.40%                ×3.78 · p=0.0001

    영업손실과 겹치지만 같지 않다 — 이익은 났는데 현금이 안 들어오는 회사(매출채권·
    재고 증가)가 여기만 걸린다. 반대로 대규모 감가상각이 있으면 적자여도 현금은 들어온다.

    주요계정 API 에는 현금흐름표가 없어서 전체 재무제표 API 로 따로 받아야 한다.
    """
    if cash is None or cash >= 0:
        return None
    label = f"{year}년 " if year else ""
    return Flag(
        kind="영업현금흐름 음수",
        summary=f"{label}영업활동현금흐름이 마이너스 — 유출 {abs(cash) / 1e8:,.0f}억",
        evidence=["영업현금흐름 음수 기업의 이후 2년 부실률 실측 3.1~6.0% "
                  "(전체 1.5~2.4% · 규모·업종 통제 후 ×3.9~7.3 · 기준시점 2개)",
                  "다만 **영업현금흐름 음수 기업의 94~97%는 2년 안에 아무 일도 "
                  "없었다** — 상장사의 33~35%가 여기 걸리고, 실제 부실의 "
                  "74~84%를 잡는다"],
    )


def interest_coverage_below_one(
    operating_income: float | None, interest: float | None, *, year: str = ""
) -> Flag | None:
    """이자보상배율 1 미만 — 영업이익으로 이자도 못 갚는다.

    기준시점 4개 × 통제 설정 7개 전부에서 유의했다:

      T=2021   해당 673사 · 이후 2년 부실 5.65%   ×3.44 · p=0.0002
      T=2022   해당 636사 · 6.29%                ×3.32 · p=0.0001
      T=2023   해당 684사 · 5.85%                ×1.82 · p=0.0044
      T=2024   해당 863사 · 7.53%                ×3.70 · p=0.0001

    영업손실이면 정의상 이자를 갚을 재원이 없으므로 여기에도 걸린다. 반대로 흑자여도
    이자가 그보다 크면 걸린다 — 부채가 많은 흑자 기업이 그렇다.

    이자비용은 실제로 나간 현금(이자의 지급)을 먼저 쓴다. 금융원가에는 외환차손·
    파생상품평가손실이 섞여 있어 배율을 실제보다 나쁘게 만든다.
    """
    if operating_income is None or interest is None or interest <= 0:
        return None
    if operating_income >= interest:
        return None
    label = f"{year}년 " if year else ""
    # 영업손실이면 배율이 음수로 나온다. "-8.4배" 는 읽는 사람에게 아무 뜻이 없고
    # 8.4배 여유가 있는 것처럼 오독될 수도 있다 — 그때는 배율 대신 말로 쓴다.
    how = (f"배율 {operating_income / interest:.2f}배" if operating_income > 0
           else "영업손실이라 이자 갚을 재원이 없다")
    return Flag(
        kind="이자보상배율 1 미만",
        summary=f"{label}영업이익으로 이자를 못 갚는다 — {how} "
                f"(영업이익 {operating_income / 1e8:,.0f}억 · 이자 {interest / 1e8:,.0f}억)",
        evidence=["이자보상배율 1 미만 기업의 이후 2년 부실률 실측 3.6~5.4% "
                  "(전체 1.5~2.4% · 규모·업종 통제 후 ×5.3~12.4 · 기준시점 2개)",
                  "다만 **이자보상배율 1 미만 기업의 95~96%는 2년 안에 아무 일도 "
                  "없었다** — 상장사의 31~39%가 여기 걸리고, 실제 부실의 "
                  "76~89%를 잡는다"],
    )


# 기준시점 전부에서 채택된 신호. 개수를 셀 때 이것만 센다 —
# 미검정·반려 신호를 섞으면 개수가 뜻을 잃는다.
#
# 여기에 **부분집합 신호는 넣지 않는다.** 현금 런웨이 2년(426사)과
# 이익잉여금/자산 하위 25%(581사)는 둘 다 채택됐지만, 이 5종에 이미 걸린 회사
# 밖으로 단 한 곳도 안 나온다(0사). 개수에 더하면 같은 회사의 숫자만 부풀어서
# 개수가 심각도로 읽히는 걸 왜곡한다. 그런 신호는 **좁혀주는 층**으로 쓴다.
ADOPTED_KINDS: tuple[str, ...] = (
    "결손금", "당기순손실", "영업손실", "영업현금흐름 음수",
    "이자보상배율 1 미만",
)

# 걸린 개수 → 실측 부실률 (기준시점 2개: 2023·2024).
#
# ⚠️ 값이 전부 바뀌었다. 답안지에서 영업정지를 뺐기 때문이다 — 하나은행(532조)·
#    신한은행 같은 대기업 제재가 부실로 세어지고 있었고, 그 회사들은 이 5종에
#    하나도 안 걸려서 낮은 구간의 부실률을 올리고 있었다. 빼니까 **0개 구간이
#    0.00~0.20%** 로 떨어졌다(전에는 1.3~1.5%).
_COUNT_RATE: tuple[tuple[int, str], ...] = (
    (0, "0.00~0.20%"),
    (1, "0.38~0.54%"),
    (2, "1.84~2.38%"),
    (3, "1.99~3.14%"),
    (4, "3.12~4.25%"),
    (5, "5.54~10.18%"),
)
_COUNT_BASES = 2


def flag_count_summary(fired: int, known: int) -> str:
    """몇 개나 걸렸는가 — 사람이 점검표를 쓰는 방식 그대로.

    신호를 하나씩 검정해왔지만, 실제 사용은 "쭉 훑고 몇 개 걸렸나" 다.

    ⚠️ **개수만으로 순서를 매기면 틀린다.** 같은 개수 안에서 이익잉여금 3년
       방향이 더 크게 가른다 (T=2024 실측):

         3개 걸림 + 악화       74사 ·  8.1%
         3개 걸림 + 악화 아님  126사 ·  0.8%      열 배
         4개 걸림 + 악화 아님   83사 ·  0.0%      부실 0건
         5개 걸림 + 악화 아님   51사 ·  5.9%

       3개 걸림 + 악화(8.1%)가 5개 걸림 + 악화 아님(5.9%)보다 높다. 그래서 이
       요약만 내면 안 되고 `direction_split` 을 같이 내야 한다.
    """
    band = next(r for n, r in reversed(_COUNT_RATE) if fired >= n)
    tag = f"{fired}개" if fired < 5 else "5개 이상"
    note = ("" if known >= len(ADOPTED_KINDS)
            else f" · 재무를 못 받아 {len(ADOPTED_KINDS) - known}종은 판정 못 함")
    return (f"채택 신호 {len(ADOPTED_KINDS)}종 중 **{tag}** 걸림 — "
            f"이 구간의 실측 부실률 {band} (기준시점 {_COUNT_BASES}개){note}")


# 같은 개수 안에서 이익잉여금 방향이 가르는 정도 (T=20240630 실측).
# 표본이 얇은 구간(0~2개)은 안 넣는다 — 없는 정밀도를 만들지 않는다.
_DIRECTION_SPLIT: dict[int, tuple[int, float, int, float]] = {
    3: (74, 8.1, 126, 0.8),
    4: (127, 7.1, 83, 0.0),
    5: (247, 12.1, 51, 5.9),
}


def direction_split(fired: int, worsening: bool | None) -> str:
    """개수가 같아도 방향이 다르면 다른 회사다.

    `worsening` 이 None 이면 **모른다**고 말한다. 3년치 이익잉여금이 다 있어야
    방향이 나오는데, 없는 걸 "악화 아님" 으로 세면 안전해 보인다.
    """
    band = _DIRECTION_SPLIT.get(min(fired, 5))
    if band is None:
        return ""
    n_bad, r_bad, n_ok, r_ok = band
    tag = f"{min(fired, 5)}개"
    if worsening is None:
        return (f"3년치 이익잉여금이 없어 **방향을 판정하지 못했습니다.** 같은 "
                f"{tag} 걸린 회사도 방향에 따라 {r_bad:.1f}% 와 {r_ok:.1f}% 로 "
                f"갈립니다 — 이 칸이 비면 그만큼 덜 아는 것입니다.")
    if worsening:
        return (f"게다가 **누적 손실이 3년째 커지는 중**입니다. 같은 {tag} 걸렸고 "
                f"방향도 악화였던 {n_bad}사 중 {r_bad:.1f}%가 부실로 갔습니다 — "
                f"방향이 악화가 아니었던 {n_ok}사는 {r_ok:.1f}%였습니다.")
    return (f"다만 **누적 손실이 커지는 중은 아닙니다.** 같은 {tag} 걸렸는데 "
            f"방향이 악화가 아니었던 {n_ok}사의 부실률은 {r_ok:.1f}%로, "
            f"악화였던 {n_bad}사({r_bad:.1f}%)보다 낮습니다.")


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
    operating_cashflow: float | None = None,
    interest_cost: float | None = None,
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
        negative_operating_cashflow(operating_cashflow, year=fiscal_year),
        interest_coverage_below_one(operating_income, interest_cost, year=fiscal_year),
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


# 감사보고서가 같은 구간 안에서 가르는 정도 (T=20240630 · 감사의견 보유 2,073사 ·
# 전체 부실률 2.56%).
#
# ⚠️ **두 시점에 걸었는데 한 시점만 판정이 났다.** 감사의견은 2021·2022·2023 을
#    갖고 있어서(한 요청에 당기·전기·전전기가 함께 온다) 두 기준시점 다 검정에
#    태울 수 있었다. 결과:
#
#      T=2023  해당 63사 · 부실률 12.70%  판정 불가 — 신호군 부실 8건 (최소 20건)
#      T=2024  해당 80사 · 부실률 31.25%  **채택** 7/7 · 최보수 ×12.28 · p<0.0005
#
#    ×12.28 은 이 저장소가 잰 것 중 **가장 강한 값**이다. 그런데 채택 신호로 올리지
#    않는다 — 다른 신호에 걸었던 "두 기준시점 전부" 를 못 넘겼고, 결과가 좋다고
#    기준을 느슨하게 바꾸면 그 기준이 무의미해진다. 막힌 건 감사 데이터가 아니라
#    **부실 라벨 수**다(영업정지를 빼면서 810→526건).
#
#    개별 표기는 더 얇아서 아예 판정이 안 난다 — 계속기업 경고 단독은 신호군 부실이
#    4·8건, 의견거절·한정 단독은 17건이다. 아래 세 갈래 숫자는 **관측**이다.
#
# 결손금 걸린 562사(8.0%)를 감사로 나눈 값이다:
_AUDIT_IN_DEFICIT: dict[str, tuple[int, float, str]] = {
    "adverse": (40, 40.0, "의견거절·한정"),
    "concern": (32, 18.8, "계속기업 경고"),
    "none": (490, 4.7, "감사 경고 없음"),
}
# 신호 5개 구간에서는 훨씬 크게 갈린다 — 여기가 이 층의 값어치다.
_AUDIT_AT_FIVE = (249, 5.2, 46, 43.5)
# 그리고 둘 다 깨끗하면 실측 부실 0건이었다.
_AUDIT_CLEAN_ZERO = (914, 0.0)


def _subject(word: str) -> str:
    """받침에 맞는 주격 조사를 붙인다 — "계속기업 경고이" 같은 게 나오면 안 된다.

    한글 음절은 0xAC00 부터 28 자씩 한 묶음이고 그 안에서 종성이 0 이면 받침이 없다.
    라벨을 사람이 늘릴 때마다 조사를 손으로 맞추면 언젠가 어긋난다.
    """
    last = word.strip()[-1]
    if not ("가" <= last <= "힣"):
        return f"{word}가"
    return f"{word}{'이' if (ord(last) - 0xAC00) % 28 else '가'}"


def audit_split(fired: int, audit: str | None, year: str | None = None) -> str:
    """감사인이 뭐라고 썼는지가 같은 개수 안에서 가른다.

    `audit` 는 'adverse'(의견거절·한정) / 'concern'(계속기업 경고) / 'none'(경고 없음)
    / None(감사의견을 못 받음). **None 을 'none' 으로 세면 안 된다** — 못 받은 것과
    경고가 없는 것은 다르다.

    `year` 는 그 판정이 어느 사업연도 것인지다. 재무와 다른 해일 수 있어서 —
    감사의견을 2023 한 해분만 받아 놨다 — 어느 해인지 밝히지 않으면 같은 해로 읽힌다.
    """
    if audit is None:
        n_ok, r_ok, n_bad, r_bad = _AUDIT_AT_FIVE
        return ("감사보고서를 받지 못해 **감사인이 뭐라 썼는지 모릅니다.** "
                f"신호 5개가 걸린 회사끼리도 감사 경고 유무로 {r_ok:.1f}%와 "
                f"{r_bad:.1f}%로 갈립니다 — 이 칸이 비면 그만큼 덜 아는 것입니다.")
    stamp = f"{year} 사업연도 감사보고서 · " if year else ""
    if audit == "none" and fired == 0:
        n, rate = _AUDIT_CLEAN_ZERO
        return (f"{stamp}감사인도 아무 경고를 달지 않았습니다. "
                f"**신호 0개 + 감사 경고 없음**"
                f"이었던 {n}사 중 이후 2년 안에 부실로 간 곳은 "
                f"**{rate:.0f}건**이었습니다 (관측 · 두 시점 중 한 시점만 판정).")
    if fired >= 5:
        n_ok, r_ok, n_bad, r_bad = _AUDIT_AT_FIVE
        if audit == "none":
            return (f"{stamp}**감사인은 경고를 달지 않았습니다.** 같은 5개 걸렸는데 "
                    f"감사 경고가 없던 {n_ok}사의 부실률은 {r_ok:.1f}%로, 경고가 "
                    f"있던 {n_bad}사({r_bad:.1f}%)의 8분의 1이었습니다 (관측 · 두 시점 중 한 시점만 판정).")
        n, rate, label = _AUDIT_IN_DEFICIT[audit]
        marked = _subject(label).replace(label, f"**{label}**", 1)
        return (f"{stamp}{marked} 있습니다. 같은 5개 걸렸고 감사 "
                f"경고까지 있던 {n_bad}사 중 {r_bad:.1f}%가 부실로 갔습니다 — 경고가 "
                f"없던 {n_ok}사는 {r_ok:.1f}%였습니다. 감사 경고 자체를 규모·업종 "
                f"통제 7설정에 걸면 **최보수 ×12.28**로, 이 저장소가 잰 것 중 가장 "
                f"강합니다 (다만 두 기준시점 중 한 시점만 판정이 났습니다).")
    n, rate, label = _AUDIT_IN_DEFICIT[audit]
    if audit == "none":
        return ""          # 신호가 적고 경고도 없으면 더 할 말이 없다
    marked = _subject(label).replace(label, f"**{label}**", 1)
    return (f"{stamp}{marked} 있습니다. 결손금이 있으면서 같은 표기를 "
            f"받았던 {n}사 중 {rate:.1f}%가 이후 2년 안에 부실로 갔습니다 — 결손금만 "
            f"있고 감사 경고는 없던 490사는 4.7%였습니다 (관측 · 두 시점 중 한 시점만 판정).")


# 공시 행태 — 재무제표가 아니라 **회사가 공시를 어떻게 다루는가**.
# 로드맵 E축인데 한 번도 못 쟀던 자리다. DART OpenAPI 에는 없고 거래소에만 있다.
#
# 감사 층과 같은 구조다 — **새 회사를 찾는 게 아니라 좁혀준다.** 실측으로 핵심 5종에
# 하나도 안 걸리면서 불성실공시만 있는 회사는 T=2023 35사·T=2024 33사인데 그중
# **부실이 0건**이다. 재무가 멀쩡하면 공시 행태만으로는 아무 뜻이 없다.
#
# 반대로 이미 걸린 회사 안에서는 크게 가른다 (걸린 개수 · 불성실공시 O/X · 부실률):
#
#            T=2023                     T=2024
#   4개   32사 9.4% / 174사 2.3%    32사  9.4% / 191사 3.1%
#   5개   58사17.2% / 249사 2.8%    67사 29.9% / 267사 5.2%
#
# 3개 구간은 양쪽 다 표본이 20사 미만이라 내지 않는다.
_BAD_DISCLOSURE_SPLIT: dict[int, tuple[int, float, int, float]] = {
    4: (32, 9.4, 191, 3.1),
    5: (67, 29.9, 267, 5.2),
}
# 핵심 5종 밖에서 불성실공시만 있는 회사 — 두 시점 다 부실 0건.
_BAD_DISCLOSURE_ALONE = (33, 0.0)


def disclosure_split(fired: int, count: int | None) -> str:
    """불성실공시 지정 이력이 같은 구간 안에서 가르는 정도.

    `count` 는 최근 3년 지정 횟수. None 은 명단을 못 받았다는 뜻이다 — 지정이
    없는 것과 다르다. 명단 자체는 전수라 보통 0 이 정상이다.
    """
    if count is None:
        return ""
    if not count:
        if fired == 0:
            return ("최근 3년에 불성실공시로 지정된 적도 없습니다.")
        return ""
    if fired < 4:
        n, rate = _BAD_DISCLOSURE_ALONE
        return (f"최근 3년에 **불성실공시 법인으로 {count}회 지정**됐습니다. 다만 재무 "
                f"신호가 별로 없을 때는 이것만으로 예고되지 않습니다 — 핵심 5종에 걸리지 "
                f"않으면서 불성실공시만 있던 {n}사 중 이후 2년 부실은 **0건**이었습니다.")
    n_bad, r_bad, n_ok, r_ok = _BAD_DISCLOSURE_SPLIT[min(fired, 5)]
    tag = f"{min(fired, 5)}개"
    return (f"게다가 최근 3년에 **불성실공시 법인으로 {count}회 지정**됐습니다. 같은 "
            f"{tag} 걸렸고 불성실공시 이력도 있던 {n_bad}사 중 {r_bad:.1f}%가 부실로 "
            f"갔습니다 — 이력이 없던 {n_ok}사는 {r_ok:.1f}%였습니다.")
