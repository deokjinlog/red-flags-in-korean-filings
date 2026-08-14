"""임계값을 실측 분포로 바꾸기 위한 기준선 수집.

왜 필요한가:
  "계열사 내부거래 13건" 은 그 자체로는 판단이 안 된다. 많은 건가? 화학·방산 계열을
  거느린 회사면 정상일 수도 있다. 지금 코드의 임계 3건은 **근거 없는 임의값**이고,
  이 프로젝트가 다른 데서는 다 거부해온 종류의 숫자다.

  분포를 재두면 "13건" 이 "동종 중위값 대비 N배 · 상위 M%" 가 된다. 그게 실제로
  판단에 쓰이는 형태다.

무엇을 재는가:
  그래프에 있는 회사들의 공정위 공시(pblntf_ty=J) 건수. 종류별로 나눠 센다 —
  자금거래와 내부거래는 분포가 다르다.

사용:
    uv run python scripts/build_baseline.py --sample 150 --year 2024
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from pathlib import Path

from dartweave.config import Settings
from dartweave.dart.client import DartClient
from dartweave.dart.status import Action, classify
from dartweave.screen.flags import FUNDING_KEYWORDS, TRADE_KEYWORDS

OUT = Path("data/baseline_fairtrade.json")


def count_for(client: DartClient, corp_code: str, year: str) -> tuple[int, int]:
    payload = client.get_json("list.json", {
        "corp_code": corp_code, "bgn_de": f"{year}0101", "end_de": f"{year}1231",
        "pblntf_ty": "J", "page_count": "100",
    })
    if classify(str(payload.get("status", ""))) is not Action.OK:
        return 0, 0
    names = [re.sub(r"\[.*?\]", "", it.get("report_nm", "")).strip()
             for it in (payload.get("list") or [])]
    funding = sum(1 for n in names if any(k in n for k in FUNDING_KEYWORDS))
    trade = sum(1 for n in names if any(k in n for k in TRADE_KEYWORDS))
    return funding, trade


def summarize(values: list[int]) -> dict[str, float | int]:
    """분포 요약. 0 이 대다수라 평균은 쓸모없고 분위수를 본다."""
    vs = sorted(values)
    n = len(vs)
    q = lambda p: vs[min(int(p * n), n - 1)]  # noqa: E731
    return {
        "n": n,
        "zero_ratio": round(sum(1 for v in vs if v == 0) / n, 4) if n else 0.0,
        "median": statistics.median(vs) if vs else 0,
        "p75": q(0.75), "p90": q(0.90), "p95": q(0.95), "p99": q(0.99),
        "max": vs[-1] if vs else 0,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--sample", type=int, default=150)
    p.add_argument("--year", default="2024")
    p.add_argument("--graph", default="data/graph_closed.json")
    args = p.parse_args(argv)

    settings = Settings.from_env()
    if not settings.dart_api_key:
        print("DART_API_KEY 가 없습니다.", file=sys.stderr)
        return 2

    raw = json.loads(Path(args.graph).read_text(encoding="utf-8"))["edges"]
    codes: list[str] = []
    for a, b, _ in raw:
        for c in (a, b):
            if c not in codes:
                codes.append(c)
    codes = codes[: args.sample]

    client = DartClient(api_key=settings.dart_api_key)
    funding, trade = [], []
    try:
        for i, code in enumerate(codes, 1):
            f, t = count_for(client, code, args.year)
            funding.append(f)
            trade.append(t)
            if i % 50 == 0:
                print(f"  {i}/{len(codes)}")
    finally:
        client.close()

    result = {
        "year": args.year,
        "sample": len(codes),
        "funding": summarize(funding),
        "trade": summarize(trade),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")

    for key in ("funding", "trade"):
        d = result[key]
        label = "특수관계인 자금거래" if key == "funding" else "계열사 내부거래"
        print(f"\n{label} — 표본 {d['n']}사 ({args.year})")
        print(f"  0건인 회사 {d['zero_ratio']:.1%}")
        print(f"  중위 {d['median']} · p75 {d['p75']} · p90 {d['p90']} "
              f"· p95 {d['p95']} · p99 {d['p99']} · 최대 {d['max']}")
    print(f"\n→ {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
