"""불성실공시 벌점 — 이진을 등급으로 바꾼다.

왜 필요한가:
  지금 파이프라인에 들어간 "최근 3년 불성실공시 이력" 은 **있다/없다** 뿐이다.
  그런데 벌점 1점짜리 한 번과 15점은 같은 사건이 아니다. 벌점을 붙이면 같은
  데이터로 좁혀주는 힘이 세진다.

  규정선도 여기서만 검증할 수 있다. 관리종목 칸은 판정선을 거래소가 정해서 우리가
  안 정했는데, 벌점은 **우리가 실측으로 선을 그을 수 있는 거의 유일한 자리**다.
  (코스닥은 누계 8점, 유가증권은 15점에서 관리종목 지정 — 시장마다 다르다.)

경로 — 한 건에 세 번:
  1) 뷰어 껍데기        common/disclsviewer.do?method=search&acptno=…
                        → <option value='{docNo}|Y'> 에서 docNo
  2) 본문 경로          common/disclsviewer.do  method=searchContents&docNo=…
                        → parent.setPath('', 'https://…/99802.htm', …)
  3) 본문               그 경로를 받아 태그를 벗긴다

  1,021건이면 3,063번이다. 간격 0.3초 기본, 이어받기, 연속 실패 10회면 정지.
  **간격을 줄이지 마라** — opendart 가 이걸로 막혔다.

본문에서 뽑는 것 (실측 예시 · 오리엔트바이오 2023-07-03):
    2. 불성실공시 유형        공시불이행
    5. 부과벌점 현황          부과벌점 0 · 기 부과벌점 0 · 누계벌점 0
    6. 공시위반제재금(원)      10,000,000
    7. 공시책임자 등 교체요구   미해당
    9. 공시위반관리종목 여부    미해당

⚠️ **벌점 0 이 "아무 일 없음" 이 아니다.** 유가증권시장은 벌점 대신 제재금을 물릴 수
   있다 — 위 예가 벌점 0 에 제재금 1,000만원이다. 벌점만 보면 이런 건이 통째로
   "가벼움" 으로 읽힌다. 제재금도 같이 뽑는 이유다.

사용:
    uv run python scripts/collect_kind_penalty.py --limit 300
"""
from __future__ import annotations

import argparse
import csv
import html as htmllib
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

VIEWER = "https://kind.krx.co.kr/common/disclsviewer.do"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
HEADERS = {"User-Agent": UA, "Referer": VIEWER}
FIELDS = ["acptno", "corp_name", "date", "kind", "imposed", "effective", "prior",
          "cumulative", "fine", "substitute", "replace_officer", "admin_flag",
          "content"]


def _get(url: str, data: bytes | None = None, timeout: int = 30) -> str:
    req = urllib.request.Request(url, data=data, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    for enc in ("utf-8", "euc-kr", "cp949"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def doc_no(acptno: str) -> str | None:
    """뷰어 껍데기에서 문서번호. 접수번호와 다른 값이다."""
    shell = _get(f"{VIEWER}?method=search&acptno={acptno}&docno=&viewerhost=&viewertype=")
    m = re.search(r"<option value='(\d{8,})\|", shell)
    return m.group(1) if m else None


def doc_url(docno: str) -> str | None:
    body = urllib.parse.urlencode({"method": "searchContents", "docNo": docno}).encode()
    page = _get(VIEWER, data=body)
    m = re.search(r"parent\.setPath\('[^']*',\s*'(https?://[^']+)'", page)
    return m.group(1) if m else None


def plain_text(url: str) -> str:
    raw = _get(url)
    raw = re.sub(r"<style.*?</style>|<script.*?</script>", " ", raw, flags=re.S)
    return re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", raw))).strip()


def _num(text: str, pattern: str) -> float | None:
    m = re.search(pattern, text)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


def parse_penalty(text: str) -> dict[str, str]:
    """본문 → 필드. 서식이 **둘**이라 양쪽을 다 본다.

    코스닥(70758):
        1. 지정내역  유형 … 부과벌점 9.0  공시위반제재금(원) 36,000,000
        2. 최근 1년간 불성실공시법인 부과벌점(당해 부과벌점 포함) 9.0   ← 누계
    유가증권(99802):
        2. 불성실공시 유형 …
        5. 부과벌점 현황  부과벌점 0 · 기 부과벌점 0 · 누계벌점 0
        6. 공시위반제재금(원) 10,000,000

    ⚠️ **부과벌점 0 이 "가벼움" 이 아니다.** 코스닥은 벌점을 제재금으로 *대체부과*
       할 수 있다 — 실측으로 코아시아씨엠이 "부과벌점 0.0" 인데 기타란에 "부과벌점은
       4.0점이며 제재금 1,600만원(4.0점×400만원)을 대체부과함" 이라고 적혀 있다.
       벌점만 보면 이런 건이 통째로 0 점으로 읽힌다. 제재금과 대체부과 여부를 같이
       뽑고, 대체부과면 제재금 ÷ 400만원으로 실질 벌점을 복원한다.

    못 찾은 건 빈 칸으로 둔다 — 0 으로 채우면 진짜 0 점과 못 가른다.
    """
    kind = re.search(r"유형\s*(공시\S+)", text)
    content = re.search(r"내용\s*(.{0,110}?)\s*(?:원공시일|사유발생일|공시일|4\.)", text)
    officer = re.search(r"교체요구\s*여부\s*(해당|미해당)", text)
    admin = re.search(r"공시위반관리종목\s*여부\s*(해당|미해당)", text)

    imposed = _num(text, r"(?<!기 )부과벌점\s*([\d,.]+)")
    # 누계는 서식마다 이름이 다르다. 유가증권은 '누계벌점', 코스닥은 '최근 1년간 …'.
    cumulative = _num(text, r"누계벌점\s*([\d,.]+)")
    if cumulative is None:
        cumulative = _num(text, r"최근\s*1년간[^0-9-]{0,60}?([\d,.]+)\s*3\.")
    fine = _num(text, r"공시위반제재금\s*\(원\)\s*([\d,]+)")

    # 대체부과 — 벌점 대신 제재금을 물린 경우. 실질 벌점을 복원한다(제재금 ÷ 400만원).
    substitute = "대체부과" in text
    effective = imposed
    if substitute:
        stated = _num(text, r"부과벌점은\s*([\d.]+)\s*점")
        if stated is not None:
            effective = stated
        elif fine:
            effective = round(fine / 4_000_000, 1)

    out: dict[str, object] = {
        "kind": (kind.group(1).strip() if kind else ""),
        "content": (content.group(1).strip() if content else ""),
        "imposed": imposed,
        "effective": effective,
        "prior": _num(text, r"기\s*부과벌점\s*([\d,.]+)"),
        "cumulative": cumulative,
        "fine": None if fine is None else int(fine),
        "substitute": "Y" if substitute else "",
        "replace_officer": (officer.group(1) if officer else ""),
        "admin_flag": (admin.group(1) if admin else ""),
    }
    return {k: ("" if v is None else (f"{v:g}" if isinstance(v, float) else str(v)))
            for k, v in out.items()}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--src", default="data/kind_bad_disclosure.csv")
    p.add_argument("--out", type=Path, default=Path("data/kind_penalty.csv"))
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--min-interval", type=float, default=0.3,
                   help="요청 간격(초). 줄이지 마라 — opendart 가 이걸로 막혔다.")
    p.add_argument("--max-consecutive-errors", type=int, default=10)
    args = p.parse_args(argv)

    src = [r for r in csv.DictReader(Path(args.src).open(encoding="utf-8"))
           if r["is_signal"] == "1" and r["acptno"]]
    done: dict[str, dict] = {}
    if args.out.exists():
        with args.out.open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                # 벌점을 하나도 못 뽑은 행은 재시도 대상으로 둔다.
                if row.get("kind") or row.get("imposed"):
                    done[row["acptno"]] = row
    todo = [r for r in src if r["acptno"] not in done]
    if args.limit:
        todo = todo[: args.limit]
    print(f"지정 {len(src):,}건 · 이미 받음 {len(done):,}건 · 이번에 {len(todo):,}건",
          file=sys.stderr)

    consecutive = 0
    try:
        for i, r in enumerate(todo, 1):
            try:
                dn = doc_no(r["acptno"])
                time.sleep(args.min_interval)
                url = doc_url(dn) if dn else None
                time.sleep(args.min_interval)
                text = plain_text(url) if url else ""
                consecutive = 0
            except Exception as e:
                consecutive += 1
                print(f"  ! {r['acptno']} {type(e).__name__} (연속 {consecutive})",
                      file=sys.stderr)
                if consecutive >= args.max_consecutive_errors:
                    print("  연속 실패 한도 — 차단으로 보고 멈춘다.", file=sys.stderr)
                    break
                time.sleep(args.min_interval * 4)
                continue
            if text:
                done[r["acptno"]] = {"acptno": r["acptno"], "corp_name": r["corp_name"],
                                     "date": r["date"], **parse_penalty(text)}
            if i % 50 == 0:
                print(f"  {i}/{len(todo)}", file=sys.stderr)
                _save(args.out, done)
            time.sleep(args.min_interval)
    finally:
        _save(args.out, done)

    got = [v for v in done.values() if v.get("cumulative")]
    print(f"\n{len(done):,}건 → {args.out} (누계벌점 확보 {len(got):,}건)", file=sys.stderr)
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
