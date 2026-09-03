"""KIND 불성실공시법인 — **라벨이 아니라 신호다.**

지금까지 KIND 에서 가져온 건 전부 답안지(상장폐지·관리종목)였다. 이건 다르다 —
기준시점 **이전**에 일어난 사건이라 feature 로 쓴다. 로드맵 E축(공시 행태)에서 한
번도 못 잰 축이고, DART OpenAPI 에는 없다.

물어볼 것: **공시를 번복·변경·불이행한 회사가 2년 안에 더 망하나.**
재무를 안 보고도 되는 질문이라, opendart 가 막힌 지금 새 신호를 만들 수 있는
유일한 쪽이다.

⚠️ 제목으로 세 가지를 갈라야 한다. 실측(2022년 236건)에서 한 표에 섞여 있다:

    불성실공시법인지정(공시번복)          ← 실제로 지정됨. 이것만 신호다
    불성실공시법인지정예고(공시불이행)     ← 아직 예고. 지정으로 안 이어질 수 있다
    불성실공시법인미지정(지정유예)         ← 심의 끝에 **지정 안 함**. 세면 안 된다
    [채권]채권상장법인불성실공시           ← 채권시장. 주식 발행사와 다르다

'미지정' 을 지정으로 세면 무혐의를 유죄로 세는 것이다. 문자열에 '지정' 이 들어
있어서 조심하지 않으면 그대로 걸린다.

⚠️ 벌점은 제목에 없다. 공시 본문에 있다. "몇 점 이상이면 위험한가" 를 재려면
   본문을 받아야 한다 — 지금은 **횟수만** 센다.

사용:
    uv run python scripts/collect_kind_bad_disclosure.py --from 2019 --to 2026 \
        --out data/kind_bad_disclosure.csv
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from collect_kind_admin_history import fetch, parse  # noqa: E402  같은 엔드포인트다

# 순서가 곧 우선순위다. '미지정' 이 '지정' 보다 **먼저** 와야 한다 —
# 뒤에 두면 "불성실공시법인미지정" 이 '지정' 으로 잡힌다.
STATUS_RULES: tuple[tuple[str, str, bool], ...] = (
    # (패턴, 이름, 신호로 세나)
    (r"\[채권\]|채권상장법인", "채권", False),
    (r"미지정", "미지정", False),
    (r"지정예고|예고", "지정예고", False),
    (r"해제|취소", "해제", False),
    (r"지정", "지정", True),
)

REASON_RULES: tuple[tuple[str, str], ...] = (
    (r"공시번복", "공시번복"),
    (r"공시변경", "공시변경"),
    (r"공시불이행", "공시불이행"),
)


def status_of(title: str) -> tuple[str, bool]:
    flat = re.sub(r"\s+", "", title)
    for pattern, name, counts in STATUS_RULES:
        if re.search(pattern, flat):
            return name, counts
    return "기타", False


def reason_of(title: str) -> str:
    flat = re.sub(r"\s+", "", title)
    hits = [name for pattern, name in REASON_RULES if re.search(pattern, flat)]
    return "+".join(hits) if hits else "사유불명"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--from", dest="frm", type=int, default=2019)
    p.add_argument("--to", dest="to", type=int, default=2026)
    p.add_argument("--out", type=Path, default=Path("data/kind_bad_disclosure.csv"))
    p.add_argument("--pause", type=float, default=0.25)
    args = p.parse_args(argv)

    seen: set[tuple[str, str, str]] = set()
    rows: list[dict] = []
    for year in range(args.frm, args.to + 1):
        got = 0
        for page in range(1, 21):
            try:
                page_rows = parse(fetch(f"{year}-01-01", f"{year}-12-31", page,
                                        report_nm="불성실공시"))
            except Exception as e:
                print(f"  ! {year} p{page} {type(e).__name__}", file=sys.stderr)
                break
            if not page_rows:
                break
            for r in page_rows:
                key = (r["date"], r["corp_name"], r["title"])
                if key in seen:
                    continue
                seen.add(key)
                status, counts = status_of(r["title"])
                rows.append({"date": r["date"], "corp_name": r["corp_name"],
                             "title": r["title"], "market": r["market"],
                             "status": status, "reason": reason_of(r["title"]),
                             "is_signal": "1" if counts else "0"})
                got += 1
            if len(page_rows) < 100:
                break
            time.sleep(args.pause)
        print(f"  {year}  {got:>4}건", file=sys.stderr)
        time.sleep(args.pause)

    rows.sort(key=lambda r: (r["date"], r["corp_name"]))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["date", "corp_name", "title", "market",
                                           "status", "reason", "is_signal"])
        w.writeheader()
        w.writerows(rows)

    st = Counter(r["status"] for r in rows)
    real = [r for r in rows if r["is_signal"] == "1"]
    print(f"\n{len(rows):,}건 → {args.out}", file=sys.stderr)
    print("  상태:", dict(st.most_common()), file=sys.stderr)
    print(f"  실제 지정 {len(real):,}건 · 회사 {len({r['corp_name'] for r in real}):,}사",
          file=sys.stderr)
    print("  사유:", dict(Counter(r["reason"] for r in real).most_common()), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
