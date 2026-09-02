"""정기보고서 「회사채 미상환 잔액」 — **막다른 길이다.** 그 측정 기록.

자금 캘린더는 지금 *발행 공시* 만 갖고 있어서, 만기 전에 주식으로 전환됐거나
조기상환된 사채도 여전히 갚을 돈으로 센다(실제 부담의 위쪽 경계). 이 API 는 회사가
직접 신고한 **미상환 잔액**을 1년 이하 / 1~2년 / … 구간으로 주므로, 그걸로 고칠 수
있어 보였다. 우리가 아예 안 갖고 있던 일반 회사채도 여기 들어온다.

**그런데 이 표에 전환사채를 안 적는 회사가 절반 가까이 된다.**

  표본 60사 (2023 재무 보유 · 스팩 제외 · 무작위)
    표는 있는데 전부 "-"   38사  63%
    잔액이 적혀 있음       20사  33%
    status 013(표 없음)    2사   3%

  그중 2023년 말에 확실히 미상환일 CB 를 가진 20사
    표에 잡힘    11사
    안 잡힘       9사   ← **거짓 음성 45%**

같은 회사가 연도에 따라 다르게 적기도 한다. 엘앤에프는 2023-04 에 CB 6,628억을
찍었는데 2023 사업보고서에는 "-", 2024 사업보고서에는 5,908억으로 나온다.

**그래서 발행액을 이 값으로 보정하지 않는다.** 보정하면 표를 자세히 쓰는 회사만
금액이 줄어 안전해 보이는데, 그건 위험의 차이가 아니라 공시 습관의 차이다. 이
저장소가 이미 한 번 걸렸던 탐지 편향("공시 많이 내면 많이 걸린다 → 층화하니 붕괴")과
같은 모양이다. 독립 신호로 세우는 것도 같은 이유로 못 한다 — "모름" 이 되는 45% 가
무작위가 아니라 공시 습관과 얽혀 있어서, 남은 표본이 어느 쪽으로 치우쳤는지 모른다.

수집기는 남겨둔다. 위 숫자를 다시 재려면 이게 필요하고, 나중에 사업보고서 본문의
「미상환 전환사채 발행현황」(ACODE 로 표시된 표)을 받게 되면 대조군이 된다.

사용:
    uv run python scripts/collect_bond_balance.py --year 2023 --limit 4000

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from dartweave.config import Settings
from dartweave.dart.client import DartClient
from dartweave.dart.status import Action, classify

OUT = Path("data/bond_balance.json")

# 만기 구간 — API 필드명 그대로. 순서가 곧 만기 순이다.
BUCKETS = (
    ("yy1_below", "1년 이하"),
    ("yy1_excess_yy2_below", "1~2년"),
    ("yy2_excess_yy3_below", "2~3년"),
    ("yy3_excess_yy4_below", "3~4년"),
    ("yy4_excess_yy5_below", "4~5년"),
    ("yy5_excess_yy10_below", "5~10년"),
    ("yy10_excess", "10년 초과"),
)


def amount(raw: object) -> float | None:
    """"891,000,000,000" → 891000000000.0 · "-" 나 공란은 None.

    0 으로 바꾸지 않는다. 안 적은 것과 0 원인 것은 다르고, 여기서 섞으면
    표를 안 쓰는 회사가 "빚 없음" 이 된다.
    """
    s = str(raw or "").replace(",", "").strip()
    if not s or s in {"-", "–", "—"}:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--year", default="2023", help="사업연도 (그 해 사업보고서)")
    p.add_argument("--limit", type=int, default=4000)
    p.add_argument("--universe", default="data/universe_listed.json")
    p.add_argument("--min-interval", type=float, default=0.25,
                   help="요청 간격(초). 너무 좁히면 IP 가 막힌다 — 한 번 겪었다.")
    args = p.parse_args(argv)

    s = Settings.from_env()
    if not s.dart_api_key:
        print("DART_API_KEY 가 없습니다.", file=sys.stderr)
        return 2

    codes = list(json.loads(Path(args.universe).read_text(encoding="utf-8")))
    book: dict[str, dict] = (
        json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    )
    year = args.year
    # 재개 조건은 **그 연도가 이미 있는가** 다. 회사 단위로 건너뛰면 다른 연도를
    # 통째로 빠뜨린다 — 재무 수집에서 이 실수를 두 번 했다.
    todo = [c for c in codes if year not in (book.get(c) or {})][: args.limit]
    if not todo:
        have = sum(1 for c in codes if year in (book.get(c) or {}))
        print(f"이어받을 게 없습니다 — {year}년 {have:,}/{len(codes):,}")
        return 0

    client = DartClient(api_key=s.dart_api_key)
    saved = 0
    try:
        for i, code in enumerate(todo, 1):
            try:
                r = client.get_json(
                    "cprndNrdmpBlce.json",
                    {"corp_code": code, "bsns_year": year, "reprt_code": "11011"})
            except Exception as e:                      # 네트워크 — 저장하지 않는다
                print(f"  ! {code} {type(e).__name__}: {str(e)[:60]}", flush=True)
                continue
            status = str(r.get("status", ""))
            act = classify(status)
            if act in (Action.RETRY, Action.ABORT):
                # 020(쿼터)·알 수 없는 코드는 멈춘다. 계속 돌면 빈 값이 정답처럼
                # 저장되고, 재개가 그걸 "받았다" 로 읽는다.
                print(f"  중단: status={status} {r.get('message')}", flush=True)
                break
            # 013(데이터 없음)은 그 보고서에 이 표가 아예 없다는 뜻이다. 표가 있는데
            # 전부 "-" 인 것과 구분해서 남긴다 — 나중에 둘을 따로 세야 할 수 있다.
            row: dict = {"buckets": {}, "total": None, "status": status}
            if act is Action.OK:
                # 공모·사모·합계 중 **합계** 행만 쓴다. 셋을 더하면 두 번 센다.
                tot = next((x for x in (r.get("list") or [])
                            if str(x.get("remndr_exprtn2", "")).strip() == "합계"), None)
                if tot is not None:
                    row["buckets"] = {k: amount(tot.get(k)) for k, _ in BUCKETS}
                    row["total"] = amount(tot.get("sm"))
                    row["stlm_dt"] = str(tot.get("stlm_dt", ""))
            # 조회는 됐는데 표가 비었으면 buckets 가 전부 None 이다 — 그게 "모름" 이다.
            book.setdefault(code, {})[year] = row
            saved += 1
            if i % 200 == 0:
                OUT.write_text(json.dumps(book, ensure_ascii=False), encoding="utf-8")
                print(f"  {i}/{len(todo)}", flush=True)
            time.sleep(args.min_interval)
    finally:
        client.close()
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(book, ensure_ascii=False), encoding="utf-8")

    have = [c for c in codes if year in (book.get(c) or {})]
    filled = [c for c in have if (book[c][year].get("total") is not None)]
    print(f"\n{year}년 · 조회 {len(have):,}사 · 잔액이 적힌 곳 {len(filled):,}사 "
          f"({len(filled) / max(len(have), 1) * 100:.0f}%)")
    print(f"→ {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
