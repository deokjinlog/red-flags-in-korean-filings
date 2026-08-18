"""relation_fact → 그래프 JSON. 수집 결과를 분석 도구가 읽는 형식으로 내보낸다.

왜 별도 단계인가:
  적재는 append-only 라 같은 관계가 여러 행이다(정정공시). 분석은 **한 시점의 한 값**이
  필요하다. `db/asof.py` 의 `latest_edges_at` 이 그 접기를 하고, 여기서는 그 결과를
  파일로 떨군다.

  시점을 인자로 받는 게 핵심이다 — `--as-of 20230630` 으로 내보내면 그때 알 수 있었던
  그래프가 나온다. 시계열이 쌓이면 연도별 그래프를 뽑아 비교할 수 있다.

사용:
    uv run python scripts/export_graph.py --as-of 20251231 --out data/graph_listed.json
"""
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from dartweave.db.asof import latest_edges_at


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--db", default="sqlite:///data/timeseries.db")
    p.add_argument("--as-of", default=date.today().strftime("%Y%m%d"),
                   help="이 시점에 알 수 있었던 것만 내보낸다 (YYYYMMDD)")
    p.add_argument("--out", default="data/graph_listed.json")
    args = p.parse_args(argv)

    with Session(create_engine(args.db)) as s:
        latest = latest_edges_at(s, args.as_of)

    edges = [[f.source_corp_code, f.target_corp_code, f.rel_type]
             for f in latest.values()]
    nodes = {v for e in edges for v in e[:2]}
    interior = sorted({f.source_corp_code for f in latest.values()})

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(
        json.dumps({"as_of": args.as_of, "edges": edges, "interior": interior},
                   ensure_ascii=False),
        encoding="utf-8")
    print(f"{args.as_of} 시점 · 노드 {len(nodes):,} · 엣지 {len(edges):,} "
          f"· 자기신고 보유 {len(interior):,}")
    print(f"→ {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
