"""상장폐지 라벨 수집 (KRX KIND) — 부실 라벨을 두껍게 만든다.

왜 필요한가:
  DART 주요사항보고 기반 부실 라벨은 기준시점당 54~75사다. 그 얇음 때문에
  자본잠식과 부채비율이 "표본 미달" 로 판정조차 못 받고 있다. 상장폐지는 거래소
  소관이라 DART 에 없다 — KIND 에서 가져온다.

**사유를 반드시 갈라야 한다.** 상장폐지 493건 중 절반 이상이 부실이 아니다:
  피흡수합병 42 · 스팩소멸합병 53 · 코스닥 이전상장 41 · 완전자회사 편입 37 ...
  이걸 부실로 세면 "합병당한 회사" 를 부실로 예측하는 셈이 되어 라벨이 오염된다.
  주요사항보고에서 해산(PFV 만기해산)을 걸러낸 것과 같은 이유다.

부실로 세는 것:
  감사의견 거절·부적정·한정 / 기업의 계속성 실질심사 / 파산 / 정기보고서 미제출
비부실로 두는 것:
  합병·스팩청산·이전상장·완전자회사화·자진폐지·지정자문인 미체결·시총 및 분산요건 미달

⚠️ '미제출' 은 양쪽에 다 나온다. **사업·반기·분기보고서** 미제출은 부실이고,
   **상장예비심사/합병상장예비심사 청구서** 미제출은 스팩이 기한을 못 지킨 것이다.
   순서를 잘못 두면 스팩 청산 60여 건이 통째로 부실로 들어간다.

사용:
    uv run python scripts/collect_delisting.py --from 2019-01-01
"""
from __future__ import annotations

import argparse
import json
import re
import time
from collections import Counter
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

URL = "https://kind.krx.co.kr/investwarn/delcompany.do"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
OUT = Path("data/delisting.json")

# 순서가 규칙이다 — 위에서부터 처음 걸리는 것으로 정한다.
RULES: list[tuple[str, tuple[str, ...]]] = [
    ("상장폐지(스팩청산)", ("상장예비심사", "합병상장예비심사", "SPAC")),
    ("상장폐지(합병)", ("합병", "완전자회사", "주식교환")),
    ("상장폐지(이전상장)", ("이전상장", "유가증권시장 상장")),
    ("상장폐지(자진)", ("상장폐지 신청", "신청에 의한 상장폐지")),
    ("상장폐지(감사의견)", ("감사의견", "감사범위")),
    ("상장폐지(실질심사)", ("기업의 계속성",)),
    ("상장폐지(파산)", ("파산",)),
    # 최종부도는 규칙이 아예 없어서 "기타" 로 떨어져 부실에서 빠지고 있었다.
    # 실측 4건(자안바이오·무송지오씨·데코앤이·맥스로텍) — 사유 문구가
    # "발행한 어음 또는 수표가 주거래은행에 의하여 최종부도로 결정되거나..." 다.
    ("상장폐지(부도)", ("최종부도",)),
    ("상장폐지(보고서 미제출)", ("사업보고서", "반기보고서", "분기보고서")),
    ("상장폐지(지정자문인)", ("지정자문인",)),
    ("상장폐지(요건 미달)", ("시가총액 미달", "분산요건", "매출액", "자본잠식")),
    ("상장폐지(해산)", ("해산",)),
    # 선박·부동산 펀드의 만기 도래. 부실이 아니라 예정된 종료다.
    ("상장폐지(존속기간 만료)", ("존속기간 만료",)),
]
DISTRESS = {"상장폐지(감사의견)", "상장폐지(실질심사)", "상장폐지(파산)",
            "상장폐지(보고서 미제출)", "상장폐지(부도)"}


def classify(reason: str) -> str:
    flat = reason.replace(" ", "")
    for label, markers in RULES:
        if any(m.replace(" ", "") in flat for m in markers):
            return label
    return "상장폐지(기타)"


def fetch(page: int, frm: str, to: str) -> str:
    body = urlencode({
        "method": "searchDelCompanySub", "forward": "delcompany_sub",
        "currentPageSize": "100", "pageIndex": str(page),
        "fromDate": frm, "toDate": to,
    }).encode()
    req = Request(URL, data=body, headers={
        "User-Agent": UA, "Referer": f"{URL}?method=searchDelCompanyMain",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"})
    with urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="ignore")


def parse(html: str) -> list[dict]:
    out = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        cells = [re.sub(r"\s+", " ", re.sub("<[^>]+>", "", c)).strip()
                 for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S)]
        if len(cells) >= 4 and cells[0].isdigit() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", cells[2]):
            out.append({"name": cells[1], "date": cells[2].replace("-", ""),
                        "reason": cells[3], "kind": classify(cells[3])})
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--from", dest="frm", default="2019-01-01")
    p.add_argument("--to", default="2026-12-31")
    p.add_argument("--pages", type=int, default=8)
    args = p.parse_args(argv)

    seen: dict[tuple[str, str], dict] = {}
    for page in range(1, args.pages + 1):
        rows = parse(fetch(page, args.frm, args.to))
        if not rows:
            break
        before = len(seen)
        for r in rows:
            seen[(r["name"], r["date"])] = r
        print(f"  page {page} · 누적 {len(seen):,}", flush=True)
        if len(seen) == before:
            break
        time.sleep(0.5)          # 남의 서버다 — 천천히

    names = json.loads(Path("data/corpcode.json").read_text(encoding="utf-8"))
    unresolved = 0
    for r in seen.values():
        code = names.get(r["name"])
        r["corp_code"] = code
        unresolved += code is None

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(list(seen.values()), ensure_ascii=False), encoding="utf-8")

    kinds = Counter(r["kind"] for r in seen.values())
    distress = [r for r in seen.values() if r["kind"] in DISTRESS]
    print(f"\n상장폐지 {len(seen):,}건 · corpCode 미해소 {unresolved}건")
    for k, n in kinds.most_common():
        mark = "← 부실" if k in DISTRESS else ""
        print(f"   {k:22s} {n:4d}  {mark}")
    print(f"\n부실로 세는 것 {len(distress):,}건 "
          f"(그중 corp_code 확보 {sum(1 for r in distress if r['corp_code']):,})")
    print(f"→ {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
