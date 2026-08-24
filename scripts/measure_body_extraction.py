"""본문 추출을 정형 API 로 채점한다 — 재기 전에는 쓰지 않는다.

왜 이 순서인가:
  본문에는 정형 API 에 없는 것들이 있다(특수관계인 거래 금액 등). 그걸 쓰려면
  **본문 추출이 얼마나 믿을 만한지** 먼저 알아야 한다. 그런데 없는 걸로는 채점을
  못 한다 — 정답이 없으니까.

  **겹치는 것으로 잰다.** 타법인 출자현황은 본문에도 있고 정형 API 에도 있다.
  같은 문서(같은 접수번호)에서 뽑아 대조하면 사람이 라벨을 달지 않고도 재현율과
  정밀도가 나오고, 그 값이 **본문 계층 전체의 상한선**이 된다.

  이 저장소는 층0 에서 fixture 107개가 다 통과한 채로 실 API 에 붙였다가 결함 11건을
  맞은 적이 있다. 파서와 fixture 가 같은 오해를 공유하면 자기완결적 허구가 된다.
  그래서 채점은 **실 응답 대 실 응답**으로만 한다.

무엇을 어떻게 맞다고 보나:
  이름은 표기가 흔들린다 — `㈜케이씨씨건설` / `(주)케이씨씨건설` / `케이씨씨건설`.
  법인 접두·접미와 공백을 지우고 비교한다. 지분율은 0.05%p 까지 같으면 일치로 본다
  (반올림 자리 차이).

사용:
    uv run python scripts/measure_body_extraction.py --limit 12
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from dartweave.config import Settings
from dartweave.dart.client import DartClient
from dartweave.dart.status import Action, classify
from dartweave.parse.body import extract_investments
from dartweave.parse.structured_rel import parse_investment

PCT_TOLERANCE = 0.05
_CORP_AFFIX = re.compile(r"주식회사|㈜|\(주\)|\(유\)|유한회사|Co\.|Ltd\.?|Inc\.?|,", re.I)
# 회사가 아닌 행 — 정형 API 가 표의 합계 줄을 그대로 한 행으로 준다.
NON_COMPANY = {"합계", "소계", "계", "총계"}


def norm(name: str) -> str:
    """표기 흔들림을 지운다. 이름이 안 맞으면 재현율이 실제보다 낮게 나온다."""
    return re.sub(r"\s+", "", _CORP_AFFIX.sub("", name or "")).lower()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--year", default="2023")
    p.add_argument("--limit", type=int, default=12)
    p.add_argument("--universe", default="data/universe_tested.json")
    p.add_argument("--out", default="data/body_extraction_score.json")
    args = p.parse_args(argv)

    s = Settings.from_env()
    if not s.dart_api_key:
        print("DART_API_KEY 가 없습니다.", file=sys.stderr)
        return 2

    codes = list(json.loads(Path(args.universe).read_text(encoding="utf-8")))
    names = {v: k for k, v in
             json.loads(Path("data/corpcode.json").read_text(encoding="utf-8")).items()}
    client = DartClient(api_key=s.dart_api_key)
    rows: list[dict] = []
    try:
        for code in codes:
            if len(rows) >= args.limit:
                break
            # 정형 API — 정답
            payload = client.get_json("otrCprInvstmntSttus.json", {
                "corp_code": code, "bsns_year": args.year, "reprt_code": "11011"})
            if classify(str(payload.get("status", ""))) is not Action.OK:
                continue
            # 정형 API 는 **합계 행을 한 줄로 준다.** 회사가 아니므로 정답에서 뺀다 —
            # 안 빼면 문서마다 정확히 하나씩 놓친 것으로 잡혀 재현율이 5%p 낮게 나온다.
            truth = {}
            for e in parse_investment(payload):
                if e.target_name and norm(e.target_name) not in NON_COMPANY:
                    truth[norm(e.target_name)] = e.share_pct
            if len(truth) < 3:
                continue

            # 같은 보고서의 원문 — 예측
            rcept_no = str((payload.get("list") or [{}])[0].get("rcept_no", ""))
            if not rcept_no:
                continue
            try:
                body = client.get_document(rcept_no)
            except Exception as exc:                     # noqa: BLE001
                print(f"  {names.get(code, code)} 원문 실패 — {type(exc).__name__}")
                continue
            got = {norm(x.name): x.share_pct for x in extract_investments(body)}

            hit = sorted(set(truth) & set(got))
            missed = sorted(set(truth) - set(got))
            extra = sorted(set(got) - set(truth))
            pct_ok = sum(1 for k in hit
                         if truth[k] is not None and got[k] is not None
                         and abs(truth[k] - got[k]) <= PCT_TOLERANCE)
            pct_cmp = sum(1 for k in hit
                          if truth[k] is not None and got[k] is not None)
            rows.append({"name": names.get(code, code), "rcept_no": rcept_no,
                         "truth": len(truth), "got": len(got), "hit": len(hit),
                         "missed": missed[:3], "extra": extra[:3],
                         "pct_ok": pct_ok, "pct_cmp": pct_cmp})
            r = rows[-1]
            print(f"  {r['name']:16s} 정답 {r['truth']:3d} · 추출 {r['got']:3d} · "
                  f"일치 {r['hit']:3d} · 지분율 {pct_ok}/{pct_cmp}", flush=True)
    finally:
        client.close()

    if not rows:
        print("채점할 문서를 못 모았습니다.")
        return 3
    t = sum(r["truth"] for r in rows)
    g = sum(r["got"] for r in rows)
    h = sum(r["hit"] for r in rows)
    ok = sum(r["pct_ok"] for r in rows)
    cmp_ = sum(r["pct_cmp"] for r in rows)
    print(f"\n문서 {len(rows)}건 · 정답 {t:,} · 추출 {g:,} · 일치 {h:,}")
    print(f"  재현율 {h / t:.1%}   (정답 중 본문에서 찾은 비율)")
    print(f"  정밀도 {h / g:.1%}   (추출한 것 중 정답에 있는 비율)")
    print(f"  지분율 일치 {ok / cmp_:.1%}  ({ok}/{cmp_} · 허용 오차 {PCT_TOLERANCE}%p)")
    Path(args.out).write_text(json.dumps(rows, ensure_ascii=False, indent=1),
                              encoding="utf-8")
    print(f"→ {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
