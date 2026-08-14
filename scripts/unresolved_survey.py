"""미해소 법인명 실측 — entity_alias 사전을 만들기 전에 무엇이 안 풀리는지부터 본다.

왜 측정이 먼저인가:
  사전을 손으로 채우는 건 비싸다. 어떤 표기가 실제로 몇 번 걸리는지 모르면
  안 나오는 이름을 넣고 자주 나오는 이름을 빠뜨린다. 층0 에서 이미 겪었다 —
  가정 위에서 만든 fixture 107개가 전부 통과했는데 실 API 를 붙이니 결함 11건이 나왔다.

무엇을 세는가:
  자연인은 corp_code 가 없어 미해소가 **정상**이므로 분모에서 뺀다(classify.py).
  남은 건 진짜 매핑 실패다. 빈도순으로 정렬해야 상위 몇 개만 넣어도 해소율이
  얼마나 오르는지 계산할 수 있다.

사용:
    uv run python scripts/unresolved_survey.py --sample 200
    uv run python scripts/unresolved_survey.py --sample 200 --refresh-corpcode
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from dartweave.config import Settings
from dartweave.dart.client import DartClient
from dartweave.dart.corpcode import parse_corpcode_zip
from dartweave.dart.status import Action, classify
from dartweave.parse.structured_rel import parse_investment, parse_major_shareholder
from dartweave.resolve.classify import EntityKind, classify_name
from dartweave.resolve.resolver import Resolver

CACHE = Path("data/corpcode.json")
YEAR, REPRT = "2024", "11011"


def load_corpcode(client: DartClient, *, refresh: bool) -> dict[str, str]:
    """이름 → corp_code. 20MB 다운로드라 캐시한다."""
    if CACHE.exists() and not refresh:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    raw = client.get_bytes("corpCode.xml", {})
    rows = parse_corpcode_zip(raw)
    table = {r.corp_name: r.corp_code for r in rows if r.corp_name and r.corp_code}
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(table, ensure_ascii=False), encoding="utf-8")
    return table


def surface_names(client: DartClient, corp_code: str) -> list[str]:
    """한 회사의 공시에 등장하는 상대편 표기들."""
    names: list[str] = []
    for path, parse in (
        ("hyslrSttus.json", parse_major_shareholder),
        ("otrCprInvstmntSttus.json", parse_investment),
    ):
        payload = client.get_json(
            path, {"corp_code": corp_code, "bsns_year": YEAR, "reprt_code": REPRT}
        )
        if classify(str(payload.get("status", ""))) is not Action.OK:
            continue
        for edge in parse(payload):
            for nm in (edge.source_name, edge.target_name):
                if nm:
                    names.append(nm)
    return names


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--sample", type=int, default=200, help="조회할 회사 수")
    p.add_argument("--refresh-corpcode", action="store_true")
    p.add_argument("--top", type=int, default=40, help="출력할 상위 미해소 수")
    args = p.parse_args(argv)

    settings = Settings.from_env()
    if not settings.dart_api_key:
        print("DART_API_KEY 가 없습니다.", file=sys.stderr)
        return 2

    client = DartClient(api_key=settings.dart_api_key)
    official = load_corpcode(client, refresh=args.refresh_corpcode)
    print(f"corpCode {len(official):,}건 (캐시 {CACHE})")

    # 이미 그래프에 등장한 회사들을 표본으로 쓴다 — 실제로 분석 대상인 집합이다.
    graph = json.loads(Path("data/graph_closed.json").read_text(encoding="utf-8"))
    codes: list[str] = []
    for a, b, _ in graph["edges"]:
        for c in (a, b):
            if c not in codes:
                codes.append(c)
    codes = codes[: args.sample]

    resolver = Resolver(official=official, aliases={})
    seen: Counter[str] = Counter()
    for i, code in enumerate(codes, 1):
        for nm in surface_names(client, code):
            seen[nm] += 1
            resolver.resolve(nm, rcept_no=code)
        if i % 25 == 0:
            print(f"  {i}/{len(codes)}")

    b = resolver.breakdown()
    print(f"\n표본 {len(codes)}사 · 표기 {b['attempts']:,}건")
    print(f"  법인 {b['corporate_attempts']:,} "
          f"(해소 {b['corporate_resolved']:,} / 미해소 {b['corporate_unresolved']:,})")
    print(f"  자연인 {b['natural_person']:,} · 등록불가 {b['unregistrable']:,} "
          f"· 판정불가 {b['unknown']:,}")
    print(f"  법인 해소율 {resolver.corporate_resolution_rate():.1%} "
          f"· 전체 {resolver.resolution_rate():.1%}")

    unresolved_corp: Counter[str] = Counter()
    for rec in resolver.unresolved:
        if classify_name(rec.surface_form) is EntityKind.CORPORATE:
            unresolved_corp[rec.surface_form] += rec.occurrences

    print(f"\n미해소 법인 표기 {len(unresolved_corp)}종 "
          f"(총 {sum(unresolved_corp.values()):,}건) — 상위 {args.top}")
    cum = 0
    total = sum(unresolved_corp.values()) or 1
    for nm, n in unresolved_corp.most_common(args.top):
        cum += n
        print(f"  {n:4d}건 ({cum/total:5.1%} 누적)  {nm}")

    out = Path("data/unresolved_corp.json")
    out.write_text(
        json.dumps(unresolved_corp.most_common(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n전체 목록 → {out}")
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
