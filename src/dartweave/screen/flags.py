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

# 신호 검정 결과를 항목 자체에 박아둔다. 검정 없이 "이상 신호" 라고 부르면
# 사용자가 위험으로 읽는다 — 실측은 반대 방향이었다.
NOT_A_RISK_NOTE = "부실과 반대 방향(검정: 먼 쪽이 2배, p=0.0007)"

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


def screen(
    edges: list[tuple[str, str, str]],
    corp_code: str,
    *,
    name=str,
    chokepoints: dict[str, int] | None = None,
    group_of: dict[str, str] | None = None,
    share_of: dict[tuple[str, str], float] | None = None,
    baseline: dict[str, dict[str, float]] | None = None,
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
    ]
    return [f for f in found if f is not None]


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
