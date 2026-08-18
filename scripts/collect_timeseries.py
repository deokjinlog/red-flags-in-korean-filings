"""연도별 관계 수집 — 재개 가능, append-only.

수천 건이라 한 번에 안 끝난다. 진행 상황을 파일에 남겨 끊긴 지점부터 이어받고,
같은 걸 다시 받아도 결과가 같다(`db/ingest.py` 가 멱등).

⚠️ 절대 덮어쓰지 않는다. 정정공시는 접수번호가 달라 새 행이 되고, 그래야
   "그때 알던 값" 을 복원할 수 있다 — `db/asof.py` 참조.

사용:
    uv run python scripts/collect_timeseries.py --years 2022,2023,2024 --limit 50
    uv run python scripts/collect_timeseries.py --years 2024 --limit 50   # 이어받기
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from dartweave.config import Settings
from dartweave.dart.client import DartClient
from dartweave.dart.status import Action, classify
from dartweave.db.ingest import ingest_edges
from dartweave.db.models import Base
from dartweave.parse.structured_rel import parse_investment, parse_major_shareholder
from dartweave.resolve.aliases import load_aliases
from dartweave.resolve.resolver import Resolver

PROGRESS = Path("data/collect_progress.json")
DB = "sqlite:///data/timeseries.db"
SOURCES = [
    ("hyslrSttus.json", parse_major_shareholder, "MAJOR_SHAREHOLDER_OF"),
    ("otrCprInvstmntSttus.json", parse_investment, "INVESTS_IN"),
]


def load_done() -> set[str]:
    if not PROGRESS.exists():
        return set()
    return set(json.loads(PROGRESS.read_text(encoding="utf-8"))["done"])


def save_done(done: set[str]) -> None:
    PROGRESS.parent.mkdir(parents=True, exist_ok=True)
    PROGRESS.write_text(json.dumps({"done": sorted(done)}, ensure_ascii=False),
                        encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--years", default="2024", help="쉼표 구분 (예: 2022,2023,2024)")
    p.add_argument("--limit", type=int, default=50, help="이번 실행에서 처리할 (기업,연도) 수")
    p.add_argument("--graph", default="data/graph_closed.json")
    p.add_argument("--db", default=DB)
    args = p.parse_args(argv)

    s = Settings.from_env()
    if not s.dart_api_key:
        print("DART_API_KEY 가 없습니다.", file=sys.stderr)
        return 2

    raw = json.loads(Path(args.graph).read_text(encoding="utf-8"))["edges"]
    codes: list[str] = []
    for a, b, _ in raw:
        for c in (a, b):
            if c not in codes:
                codes.append(c)

    years = [y.strip() for y in args.years.split(",") if y.strip()]
    todo = [f"{c}:{y}" for y in years for c in codes]
    done = load_done()
    batch = [k for k in todo if k not in done][: args.limit]
    if not batch:
        print(f"이어받을 게 없습니다 — {len(done):,}/{len(todo):,} 완료")
        return 0

    Path("data").mkdir(exist_ok=True)
    engine = create_engine(args.db)
    Base.metadata.create_all(engine)
    official = json.loads(Path("data/corpcode.json").read_text(encoding="utf-8"))
    resolver = Resolver(official=official, aliases=load_aliases())
    resolve = lambda nm: resolver.resolve(nm or "", rcept_no="ts").corp_code  # noqa: E731
    client = DartClient(api_key=s.dart_api_key)
    ins = dup = inc = 0
    try:
        with Session(engine) as sess:
            for i, key in enumerate(batch, 1):
                code, year = key.split(":")
                for path, parse, rel in SOURCES:
                    payload = client.get_json(path, {
                        "corp_code": code, "bsns_year": year, "reprt_code": "11011"})
                    if classify(str(payload.get("status", ""))) is not Action.OK:
                        continue
                    r = ingest_edges(sess, parse(payload), rel_type=rel, resolve=resolve)
                    ins += r.inserted
                    dup += r.skipped_duplicate
                    inc += r.skipped_incomplete
                done.add(key)
                if i % 20 == 0:
                    sess.commit()
                    save_done(done)
                    print(f"  {i}/{len(batch)} · 적재 {ins:,}")
            sess.commit()
    finally:
        client.close()
        save_done(done)

    print(f"\n이번 실행 {len(batch)}건 · 적재 {ins:,} · 중복 {dup:,} · 코드미상 {inc:,}")
    print(f"진행 {len(done):,}/{len(todo):,} — 다시 실행하면 이어받습니다")
    print(f"→ {args.db}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
