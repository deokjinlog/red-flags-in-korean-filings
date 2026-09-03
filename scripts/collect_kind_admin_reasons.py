"""관리종목 '사유불명' 을 공시 본문으로 채운다 — 이건 결측이 아니라 **편향**이다.

시장에 따라 제목이 다르다:
    코스닥    관리종목지정(파산신청)      ← 괄호에 사유를 쓴다
    유가증권   관리종목지정               ← 안 쓴다

실측 2026-09-03: 신규 지정 중 사유가 제목에 없는 **107건이 전부 유가증권시장본부**다.
그냥 두면 유가증권 회사만 라벨에서 빠진다. 부실이 시장별로 다르게 잡히는 답안지가
되는 것이고, 그건 신호가 아니라 **수집 방식이 만든 편향**이다. 이 저장소가 이미 한 번
겪은 모양이다 — 재무 표본을 지분 그래프 안으로 좁혀놨다가 커버리지 편향을 만들었다.

본문 구조 (유가증권 관리종목 지정 공시):
    관리종목 지정
    1. 종목명            …
    2. 관리종목 지정일    …
    3. 관리종목 지정사유   - 회생절차개시신청
    4. 근거규정          유가증권시장상장규정 제47조

'3. …지정사유' 와 '4. 근거규정' 사이를 읽는다.

⚠️ 규모·유동성(시가총액·주가 미달)은 부실로 세지 않는다 — "작다" 는 뜻이지 나빠졌다는
   뜻이 아니고, 우리가 층으로 통제하는 그 규모와 정면으로 충돌한다.

사용:
    uv run python scripts/collect_kind_admin_reasons.py --min-interval 0.3
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from collect_kind_admin_history import reason_of              # noqa: E402
from collect_kind_penalty import doc_no, doc_url, plain_text   # noqa: E402

import re

FIELDS = ["acptno", "date", "corp_name", "market", "reason_text",
          "reason", "is_distress", "rule"]


def parse_reason(text: str) -> tuple[str, str]:
    """(사유 문구, 근거규정). 못 찾으면 빈 문자열 — 지어내지 않는다."""
    clean = re.sub(r"[^가-힣A-Za-z0-9 .,%()·ㆍ\-~]", " ", text)
    clean = re.sub(r"\s+", " ", clean)
    m = re.search(r"관리종목\s*지정\s*사유\s*[-–]?\s*(.{2,140}?)\s*\d\s*\.\s*근거규정", clean)
    if not m:
        m = re.search(r"지정\s*사유\s*[-–]?\s*(.{2,140}?)\s*\d\s*\.", clean)
    rule = re.search(r"근거규정\s*(.{2,70}?)\s*\d\s*\.", clean)
    return (m.group(1).strip(" -–") if m else "",
            rule.group(1).strip() if rule else "")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--history", type=Path, default=Path("data/kind_admin_history.csv"))
    p.add_argument("--out", type=Path, default=Path("data/kind_admin_reasons.csv"))
    p.add_argument("--min-interval", type=float, default=0.3)
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--max-consecutive-errors", type=int, default=10)
    args = p.parse_args(argv)

    rows = list(csv.DictReader(args.history.open(encoding="utf-8")))
    if rows and "acptno" not in rows[0]:
        raise SystemExit("acptno 컬럼이 없다 — collect_kind_admin_history.py 를 다시 돌려라.")
    targets = [r for r in rows if r["event"] == "지정"
               and r["reason"] in ("사유불명", "기타사유") and r["acptno"]]

    done: dict[str, dict] = {}
    if args.out.exists():
        for row in csv.DictReader(args.out.open(encoding="utf-8")):
            if row.get("reason_text"):
                done[row["acptno"]] = row
    todo = [t for t in targets if t["acptno"] not in done]
    if args.limit:
        todo = todo[: args.limit]
    print(f"사유불명 {len(targets)}건 · 이미 받음 {len(done)} · 이번에 {len(todo)}",
          file=sys.stderr)

    consecutive = 0
    try:
        for i, t in enumerate(todo, 1):
            try:
                dn = doc_no(t["acptno"])
                time.sleep(args.min_interval)
                url = doc_url(dn) if dn else None
                time.sleep(args.min_interval)
                text = plain_text(url) if url else ""
                consecutive = 0
            except Exception as e:
                consecutive += 1
                print(f"  ! {t['acptno']} {type(e).__name__} (연속 {consecutive})",
                      file=sys.stderr)
                if consecutive >= args.max_consecutive_errors:
                    print("  연속 실패 한도 — 멈춘다.", file=sys.stderr)
                    break
                time.sleep(args.min_interval * 4)
                continue
            if text:
                reason_text, rule = parse_reason(text)
                # 제목 분류기를 그대로 재사용한다 — 사유 문구를 괄호에 넣어 통과시킨다.
                # 규칙이 한 벌이어야 제목에서 온 것과 본문에서 온 것이 같은 잣대를 쓴다.
                bucket, distress = reason_of(f"관리종목지정({reason_text})")
                done[t["acptno"]] = {
                    "acptno": t["acptno"], "date": t["date"],
                    "corp_name": t["corp_name"], "market": t["market"],
                    "reason_text": reason_text, "reason": bucket,
                    "is_distress": "" if distress is None else ("1" if distress else "0"),
                    "rule": rule,
                }
            if i % 25 == 0:
                print(f"  {i}/{len(todo)}", file=sys.stderr)
                _save(args.out, done)
            time.sleep(args.min_interval)
    finally:
        _save(args.out, done)

    from collections import Counter
    got = [v for v in done.values() if v["reason_text"]]
    print(f"\n{len(done)}건 → {args.out} (사유 추출 {len(got)}건)", file=sys.stderr)
    print("  버킷:", dict(Counter(v["reason"] for v in done.values()).most_common()),
          file=sys.stderr)
    print(f"  부실로 세는 것 {sum(1 for v in done.values() if v['is_distress'] == '1')}건",
          file=sys.stderr)
    left = [v for v in done.values() if v["reason"] in ("사유불명", "기타사유")]
    if left:
        print(f"  ! 아직 못 가른 {len(left)}건 — 서식이 또 다르다. 규칙을 고쳐라.",
              file=sys.stderr)
    return 0


def _save(out: Path, done: dict[str, dict]) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        for k in sorted(done):
            w.writerow({f: done[k].get(f, "") for f in FIELDS})


if __name__ == "__main__":
    raise SystemExit(main())
