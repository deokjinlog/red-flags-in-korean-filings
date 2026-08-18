"""종목 하나의 지배구조 이상 신호 — "사도 되나" 에 근거로 답한다.

이 도구는 **판단하지 않는다.** 점수도 매기지 않고 매수·매도를 말하지 않는다.
"무엇이 걸렸고 그게 어느 엣지에서 나왔는가" 만 낸다. 반박하려면 그 엣지를 반박해야 한다.

사용:
    uv run python scripts/check_company.py --name 케이씨씨
    uv run python scripts/check_company.py --name 태영건설 --graph data/graph_closed.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import igraph as ig

from dartweave.config import Settings
from dartweave.dart.client import DartClient
from dartweave.dart.status import Action, classify
from dartweave.parse.structured_rel import parse_investment, parse_major_shareholder
from dartweave.resolve.aliases import load_aliases
from dartweave.resolve.resolver import Resolver
from dartweave.screen.flags import funding_rarity, screen, trade_rarity
from dartweave.structure.interpret import allowed_tokens, build_prompt
from dartweave.structure.project import project

# 공식 기업집단 라벨. **지금은 손으로 넣은 표본이다** — 제대로 하려면 공정거래위원회
# 기업집단포털을 붙여야 하고, DART 에는 이 데이터가 없다. 라벨이 없는 회사는
# 계열 경계 검사를 건너뛴다(모르는 걸 '넘었다' 로 세지 않기 위해).
OFFICIAL_GROUPS: dict[str, str] = {
    "현대자동차": "현대차", "기아": "현대차", "현대모비스": "현대차", "현대제철": "현대차",
    "HD현대": "HD현대", "HD한국조선해양": "HD현대", "HD현대일렉트릭": "HD현대",
    "케이씨씨": "KCC", "케이씨씨글라스": "KCC",
    "현대지에프홀딩스": "현대백화점", "현대그린푸드": "현대백화점",
    "삼성전자": "삼성", "삼성물산": "삼성", "삼성생명": "삼성", "삼성화재해상보험": "삼성",
    "한화": "한화", "한화솔루션": "한화", "한화오션": "한화", "한화에어로스페이스": "한화",
    "태영건설": "태영", "티와이홀딩스": "태영",
}
TOP_CHOKEPOINTS = 12  # 매개중심성 상위 몇 위까지를 '공동 의존점' 으로 볼 것인가


def load_names() -> dict[str, str]:
    cache = Path("data/corpcode.json")
    if not cache.exists():
        print("data/corpcode.json 이 없습니다. "
              "먼저 `uv run python scripts/unresolved_survey.py --sample 1` 로 캐시하세요.",
              file=sys.stderr)
        raise SystemExit(2)
    return {v: k for k, v in json.loads(cache.read_text(encoding="utf-8")).items()}


def rank_chokepoints(edges: list[tuple[str, str, str]], top: int) -> dict[str, int]:
    """매개중심성 상위 = 끊으면 여러 묶음이 갈라지는 지점. 순위를 매겨 돌려준다."""
    g = project(edges, undirected=True)
    g.simplify()
    btw = g.betweenness()
    ordered = sorted(zip(g.vs["corp_code"], btw), key=lambda x: -x[1])[:top]
    return {code: i + 1 for i, (code, _) in enumerate(ordered)}


def fetch_shares(
    corp_codes: list[str], year: str, official: dict[str, str]
) -> dict[tuple[str, str], float]:
    """지분율을 API 로 가져온다. 캐시된 그래프에는 없다.

    지분율이 없어서 0.06% 보유를 "상호출자" 로 경고한 사고가 났다.

    **상대편 것도 같이 조회해야 한다.** 삼양사가 태영건설을 0.06% 보유한 사실은
    삼양사의 공시에 있지 태영건설 공시에 없다. 대상 종목만 보면 그 절반을 놓친다.
    전체 재수집은 필요 없고, 걸린 상대 몇 곳만 더 보면 된다.

    **이름을 코드로 되돌려야 한다.** 정형 공시는 상대편을 `corp_code` 가 아니라
    이름으로만 준다(`nm`·`inv_prm`). 해소기를 안 태우면 전부 버려져 조회 0건이 된다.
    """
    settings = Settings.from_env()
    if not settings.dart_api_key:
        return {}
    out: dict[tuple[str, str], float] = {}
    resolver = Resolver(official=official, aliases=load_aliases())
    client = DartClient(api_key=settings.dart_api_key)
    try:
        for corp_code in corp_codes:
            for path, parse, outbound in (
                ("otrCprInvstmntSttus.json", parse_investment, True),
                ("hyslrSttus.json", parse_major_shareholder, False),
            ):
                payload = client.get_json(
                    path,
                    {"corp_code": corp_code, "bsns_year": year, "reprt_code": "11011"},
                )
                if classify(str(payload.get("status", ""))) is not Action.OK:
                    continue
                for e in parse(payload):
                    other = e.target_corp_code if outbound else e.source_corp_code
                    if not other:
                        surface = e.target_name if outbound else e.source_name
                        other = resolver.resolve(
                            surface or "", rcept_no=corp_code
                        ).corp_code
                    if not other or e.share_pct is None:
                        continue
                    key = (corp_code, other) if outbound else (other, corp_code)
                    out[key] = max(out.get(key, 0.0), e.share_pct)
    finally:
        client.close()
    return out


def fetch_fairtrade(corp_code: str, year: str) -> list[tuple[str, str]]:
    """공정거래위원회 공시(pblntf_ty=J) 목록.

    본문을 안 읽어도 **공시 종류와 건수**만으로 사실이다 — "작년에 특수관계인
    자금차입을 6번 공시했다" 는 반박하려면 그 공시를 반박해야 한다.
    """
    settings = Settings.from_env()
    if not settings.dart_api_key:
        return []
    out: list[tuple[str, str]] = []
    client = DartClient(api_key=settings.dart_api_key)
    try:
        payload = client.get_json("list.json", {
            "corp_code": corp_code, "bgn_de": f"{year}0101", "end_de": f"{year}1231",
            "pblntf_ty": "J", "page_count": "100",
        })
        if classify(str(payload.get("status", ""))) is Action.OK:
            for it in (payload.get("list") or []):
                out.append((re.sub(r"\D", "", str(it.get("rcept_dt", ""))),
                            re.sub(r"\[.*?\]", "", it.get("report_nm", "")).strip()))
    finally:
        client.close()
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--name", required=True, help="종목명 (예: 케이씨씨)")
    p.add_argument("--graph", default="data/graph_listed.json")
    p.add_argument("--hops", type=int, default=2, help="공동 의존점 근접 판정 홉수")
    p.add_argument("--year", default="2024", help="지분율 조회 사업연도")
    p.add_argument("--explain", action="store_true",
                   help="걸린 항목을 문장으로 옮길 프롬프트와 허용 토큰을 함께 낸다")
    p.add_argument("--no-fetch", action="store_true",
                   help="지분율 조회를 건너뛴다 (근거에 '미상' 으로 표시됨)")
    args = p.parse_args(argv)

    names = load_names()
    by_name = {v: k for k, v in names.items()}
    code = by_name.get(args.name)
    if not code:
        print(f"'{args.name}' 을 corpCode 에서 찾지 못했습니다.", file=sys.stderr)
        return 2

    path = Path(args.graph)
    if not path.exists():
        print(f"그래프 파일이 없습니다: {path}", file=sys.stderr)
        return 2
    raw = json.loads(path.read_text(encoding="utf-8"))["edges"]
    edges = [(a, b, "MAJOR_SHAREHOLDER_OF") for a, b, _ in raw]

    if code not in {v for e in edges for v in e[:2]}:
        print(f"{args.name} 은 이 그래프에 없습니다 "
              f"(수집 범위 밖 — 그래프 {len({v for e in edges for v in e[:2]}):,}개사)",
              file=sys.stderr)
        return 3

    nm = lambda c: names.get(c, c)  # noqa: E731
    print(f"\n{args.name} ({code})")
    print(f"  지분 관계   출자 {sum(1 for a, _, _ in edges if a == code)}곳 · "
          f"피출자 {sum(1 for _, b, _ in edges if b == code)}곳")

    group_of = {by_name[n]: g for n, g in OFFICIAL_GROUPS.items() if n in by_name}
    if code in group_of:
        print(f"  공식 집단   {group_of[code]}")

    # 서로 보유하는 상대는 그쪽 공시도 봐야 지분율이 나온다.
    outs = {b for a, b, _ in edges if a == code}
    ins = {a for a, b, _ in edges if b == code}
    to_fetch = [code, *sorted(outs & ins)]
    shares = (
        None if args.no_fetch
        else fetch_shares(to_fetch, args.year, {v: k for k, v in names.items()})
    )
    if shares is not None:
        print(f"  지분율 조회   {len(shares)}건 · 대상 {len(to_fetch)}개사 "
              f"({args.year} 사업보고서)")

    gbp = Path("data/baseline_graph.json")
    gbase = json.loads(gbp.read_text(encoding="utf-8")) if gbp.exists() else {}
    if gbase:
        print(f"  그래프 기준선 {gbase.get('nodes'):,}개사 전수")
    flags = screen(
        edges, code, name=nm,
        chokepoints=rank_chokepoints(edges, TOP_CHOKEPOINTS),
        group_of=group_of,
        share_of=shares,
        baseline=gbase,
    )

    if not args.no_fetch:
        reports = fetch_fairtrade(code, args.year)
        print(f"  공정위 공시   {len(reports)}건 ({args.year})")
        base = {}
        bp = Path("data/baseline_fairtrade.json")
        if bp.exists():
            base = json.loads(bp.read_text(encoding="utf-8"))
            print(f"  기준선        표본 {base.get('sample')}사 ({base.get('year')})")
        else:
            print("  기준선        없음 — `scripts/build_baseline.py` 로 먼저 재세요")
        flags += [f for f in (funding_rarity(reports, base.get("funding")),
                              trade_rarity(reports, base.get("trade")))
                  if f is not None]

    if not flags:
        print("\n걸린 항목 없음")
        print("  ※ '이상 없음' 이 아니라 '이 검사들에는 안 걸렸음' 이다.")
    else:
        print(f"\n걸린 항목 {len(flags)}건")
        for f in flags:
            print(f"\n  [{f.kind}] {f.summary}")
            for line in f.evidence:
                print(f"      {line}")

    if args.explain and flags:
        payload = json.dumps(
            {"company": args.name,
             "flags": [{"kind": f.kind, "summary": f.summary, "evidence": f.evidence}
                       for f in flags]},
            ensure_ascii=False,
        )
        print("\n--- 해석 프롬프트 (모델에 넣을 입력) ---")
        print(build_prompt(payload))
        print(f"--- 허용 토큰 {len(allowed_tokens(payload))}개 ---")
        print("모델 출력은 interpret() 를 거쳐야 한다 — 이 토큰 밖의 숫자나 "
              "기업명이 나오면 HallucinationDetected 로 중단된다.")

    print("\n검사 범위 — 지분 관계 + 공정위 공시. 재무제표는 아직 안 본다.")
    print("이 도구는 매수·매도를 말하지 않는다. 걸린 것과 그 근거만 낸다.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
