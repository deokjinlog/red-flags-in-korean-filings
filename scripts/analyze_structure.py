"""구조 분석 CLI — analyze() 를 부르는 껍데기.

로직은 전부 `dartweave.structure.pipeline` 에 있다. CLI 가 두꺼워지면 층2가
같은 로직을 재작성하게 되고, 실행 환경에 로직이 묶이면 층0의 run_stage.py 갭이
반복된다.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dartweave.structure.evidence import to_json
from dartweave.structure.lens import LENSES
from dartweave.structure.pipeline import AnalysisConfig, QualityGateFailed, analyze
from dartweave.structure.topology import BoundaryNotClosed
from dartweave.structure.weight import EdgeEvidence

GRAPH_SHAPE = "{edges: [[a,b,type]], interior: [], evidence?: [{...}]}"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--graph", required=True, help=GRAPH_SHAPE)
    p.add_argument("--lens", required=True, choices=sorted(LENSES), metavar="LENS")
    p.add_argument("--resolution-rate", type=float, default=1.0)
    p.add_argument("--min-resolution-rate", type=float, default=0.8)
    p.add_argument("--max-boundary-ratio", type=float, default=0.0)
    p.add_argument("--null-runs", type=int, default=20)
    p.add_argument("--industry", default="미지정", help="AC-13 분석 범위 표기")
    p.add_argument(
        "--require-topology",
        action="store_true",
        help="경계가 열려 있으면 부분 산출 대신 중단한다 (exit 4)",
    )
    p.add_argument("--fiscal-year", default="2024")

    try:
        args = p.parse_args(argv)
    except SystemExit:
        print(f"사용 가능한 렌즈: {', '.join(sorted(LENSES))}", file=sys.stderr)
        return 2

    path = Path(args.graph)
    if not path.exists():
        print(f"그래프 파일을 찾을 수 없습니다: {path}", file=sys.stderr)
        return 2

    payload = json.loads(path.read_text(encoding="utf-8"))
    edges = [tuple(e) for e in payload["edges"]]
    interior = set(payload["interior"])
    raw_ev = payload.get("evidence")
    evidence = (
        [
            EdgeEvidence(
                is_structured=bool(r["is_structured"]),
                cross_confirmed=bool(r["cross_confirmed"]),
                mention_count=int(r["mention_count"]),
                share_pct=r.get("share_pct"),
                observed_precision=r.get("observed_precision"),
            )
            for r in raw_ev
        ]
        if raw_ev
        else None
    )

    cfg = AnalysisConfig(
        min_corporate_resolution_rate=args.min_resolution_rate,
        max_boundary_ratio=args.max_boundary_ratio,
        null_runs=args.null_runs,
        require_topology=args.require_topology,
        industry=args.industry,
        fiscal_year=args.fiscal_year,
    )
    try:
        block = analyze(
            edges,
            interior=interior,
            lens_name=args.lens,
            corporate_resolution_rate=args.resolution_rate,
            evidence=evidence,
            config=cfg,
        )
    except QualityGateFailed as e:
        print(f"[품질 게이트] {e}", file=sys.stderr)
        return 3
    except BoundaryNotClosed as e:
        print(f"[경계 게이트] {e}", file=sys.stderr)
        return 4

    print(to_json(block))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
