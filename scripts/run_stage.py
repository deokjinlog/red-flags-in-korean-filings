"""단계 실행 엔트리.

사용:
    uv run python scripts/run_stage.py --from load
    uv run python scripts/run_stage.py --only export

DART_API_KEY 가 필요한 단계(select/collect)는 키가 없으면 명확히 중단한다.
"""
from __future__ import annotations

import argparse
import sys

from dartweave.config import Settings

# ⚠️ RISK(side-effect): 모듈 최상단 import 라, 이 모듈이 하나라도 깨지면 main() 의 친절한
# 안내(exit 2 + --from parse 우회)에 도달하기 전에 raw traceback 으로 죽는다(exit 1).
# 실제로 Task 22 착지 전까지 db.session 이 없어 그렇게 동작했다. 의존이 늘어나면
# 지연 import 로 옮기고 main() 안에서 잡아 안내하는 편이 안전하다.
# — by main(3-checklist: 실패 경로가 설계 의도를 우회)
from dartweave.db.session import init_schema, make_engine
from dartweave.pipeline import Stage, resolve_stage, stages_from

NEEDS_API_KEY = {Stage.SELECT, Stage.COLLECT}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--from", dest="start", help="이 단계부터 끝까지")
    group.add_argument("--only", dest="only", help="이 단계만")
    args = parser.parse_args(argv)

    settings = Settings.from_env()
    targets = (
        [resolve_stage(args.only)]
        if args.only
        else stages_from(resolve_stage(args.start))
    )

    if any(s in NEEDS_API_KEY for s in targets) and not settings.dart_api_key:
        print(
            "DART_API_KEY 가 없어 select/collect 를 실행할 수 없습니다.\n"
            "  - 키 발급: https://opendart.fss.or.kr/\n"
            "  - 키 없이 진행하려면: --from parse (계약 fixture 기반)",
            file=sys.stderr,
        )
        return 2

    init_schema(make_engine(settings))
    for stage in targets:
        print(f"[stage] {stage.value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
