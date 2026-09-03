"""KIND 관리종목 **지정 이력** — 스냅샷이 아니라 사건 단위.

왜 필요한가:
  관리종목은 상장폐지보다 이른 신호라 라벨로 더 낫다. 그런데 KIND 의 '관리종목 현황'
  화면은 **지금 지정된 종목만** 준다 — 해제됐거나 이미 폐지된 회사가 빠지므로 과거
  시점 라벨로 쓰면 생존편향이 생긴다. 그래서 이 저장소는 한 번 반려했다.

  공시 상세검색으로는 다르다. 보고서명에 '관리종목' 이 든 공시를 날짜 구간으로 훑으면
  지정·해제·사유추가가 **일어난 날짜와 함께** 남는다. 시점 분리가 되는 라벨이다.

⚠️ 그냥 부실로 세면 안 되는 것 셋 (실측 2019~2026):

  1. **시가총액·주가 미달은 부실이 아니라 "작다" 는 뜻이다.** 이걸 부실로 세면 신호가
     규모를 다시 재게 되고, 우리가 7설정으로 통제하는 그 규모와 정면으로 충돌한다.
  2. **2026년에 규모·유동성 지정이 튄다.** 그전 연도는 한 자릿수였다. 회사가 나빠진 게
     아니라 거래소 요건이 바뀐 것이다(2026-07 상장폐지 개혁방안 시행). 규칙이 바뀐 해를
     라벨로 쓰면 답안지가 그 해만 다른 자를 쓴다.
  3. **사유가 제목에 없는 건이 있다**('관리종목지정', '관리종목지정사유발생').
     사유는 공시 본문에 있다. `사유불명` 으로 둔다 — 없음이 아니라 **모름**이다.

⚠️ 공시 상세검색은 **빈 값이라도 파라미터가 있어야** 결과를 준다. 최소 집합으로
   부르면 200 OK 에 0건이 온다 — 조용히 틀리는 종류라 아래 REQUIRED_EMPTY 에 박아뒀다.


⚠️ **페이지 끝을 넘기면 빈 응답이 아니라 마지막 장을 되풀이해서 준다.** 실측으로
   2019년 관리종목은 4장(46행)이 끝인데 5장·9장을 요청해도 같은 46행이 온다.
   마지막 장이 정확히 100행이면 "행 수가 100 미만이면 중단" 이 안 걸려서 같은 장을
   계속 받는다. 중복 제거가 있어 데이터는 안 틀리지만 요청은 낭비되고, 중복 제거를
   빼는 순간 조용히 몇 배로 불어난다. **직전 장과 같으면 멈춘다.**

사용:
    uv run python scripts/collect_kind_admin_history.py --from 2019 --to 2026 \
        --out data/kind_admin_history.csv
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

URL = "https://kind.krx.co.kr/disclosure/details.do"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

# 값이 비어 있어도 **키가 있어야** 한다. 빼면 200 OK 에 0건이 온다.
REQUIRED_EMPTY = ("searchCodeType", "repIsuSrtCd", "allRepIsuSrtCd",
                  "oldSearchCorpName", "disclosureType", "disTypevalue",
                  "reportCd", "searchCorpName", "isurCd", "marketType",
                  "settlementMonth", "business", "enterprise", "securities",
                  "kosdaqSegment", "lastReport", "submitOblgNm")

# 사건 유형 — 제목으로 가른다. 순서가 곧 우선순위다.
#
# ⚠️ "지정" 이라는 글자만 보면 안 된다. 실측으로 걸린 것 셋:
#   · "내부결산시점 관리종목 지정ㆍ형식적 상장폐지ㆍ상장적격성 실질심사 사유 발생" 367건
#     — 거래소의 지정이 아니라 **회사가 스스로** 사유가 생겼다고 알리는 공시다.
#   · "주권매매거래정지(관리종목지정사유발생)" 78건 — 거래정지이지 지정이 아니다.
#   · "신주인수권증권 상장폐지(기초주권의 관리종목 지정)" — 그 회사가 아니라 파생상품이다.
#   셋을 지정으로 세면 같은 사건을 여러 번 세게 된다.
EVENT_RULES: tuple[tuple[str, str], ...] = (
    (r"ETF|ETN|상장지수", "ETF"),
    (r"신주인수권|기초주권", "파생상품"),
    (r"내부결산", "내부결산 사유발생"),
    (r"매매거래정지|거래정지", "거래정지"),
    (r"소속부", "소속부변경"),
    (r"기타시장안내|시장안내", "시장안내"),
    (r"지정우려|지정예고|우려안내", "지정우려"),
    (r"일부해제|사유일부", "사유 일부해제"),
    (r"해제", "해제"),
    (r"사유추가", "사유추가"),
    (r"사유변경", "사유변경"),
    (r"지정", "지정"),
)

# 지정 사유 — 괄호 안 문구로 가른다. 부실로 셀 것과 아닌 것을 분명히 나눈다.
REASON_RULES: tuple[tuple[str, str, bool], ...] = (
    # (패턴, 묶음 이름, 부실로 세나)
    # 스팩이 먼저다. "상장예비심사청구서 미제출" 94건이 폐지절차로 들어가면
    # 껍데기의 예정된 청산이 부실로 세어진다.
    (r"SPAC|스팩|상장예비심사|합병상장예비심사", "스팩", False),
    # "기타 공익 실현과 투자자 보호" 는 유가증권 상장규정의 상장적격성 실질심사
    # 사유다. 제목에는 안 나오고 본문에만 나온다 — 본문에서 온 것도 같은 잣대를
    # 써야 해서 여기 넣는다.
    (r"상장폐지|실질심사|폐지사유|공익실현|공익", "폐지절차", True),
    (r"회생|파산|부도", "법적절차", True),
    (r"자본잠식", "자본잠식", True),
    (r"의견거절|부적정|한정|감사의견|검토의견", "감사", True),
    (r"법인세비용차감전|계속사업손실|영업손실|매출액|자기자본", "손익요건", True),
    (r"보고서\s*미제출|공시위반|공시의무|불성실공시|공시번복", "공시요건", True),
    # 아래는 부실로 세지 않는다 — 규모는 우리가 층으로 통제하는 축이다.
    (r"시가총액|주가|거래량|상장주식수|주식분산|소액주주|거래실적부진",
     "규모·유동성", False),
    (r"사외이사|감사위원회|지배구조", "지배구조", False),
)


def event_of(title: str) -> str:
    flat = re.sub(r"\s+", "", title)
    for pattern, name in EVENT_RULES:
        if re.search(pattern.replace(r"\s*", ""), flat):
            return name
    return "기타"


def reason_of(title: str) -> tuple[str, bool | None]:
    """(사유 묶음, 부실로 세나). 제목에 사유가 없으면 (사유불명, None) — 모름이다."""
    # 탐욕적으로 마지막 닫는 괄호까지 잡는다. 중첩 괄호가 있어서다 —
    # "관리종목지정(반기검토(감사)의견 부적정, ...)" 를 비탐욕으로 자르면
    # "반기검토(감사" 만 남아 '부적정' 을 못 본다. 실측 21건이 그렇게 새고 있었다.
    inside = re.search(r"[(（](.*)[)）]", title)
    text = inside.group(1) if inside else ""
    if not text.strip():
        return "사유불명", None
    flat = re.sub(r"\s+", "", text)
    for pattern, name, distress in REASON_RULES:
        if re.search(pattern.replace(r"\s*", ""), flat):
            return name, distress
    return "기타사유", None


def fetch(frm: str, to: str, page: int, size: int = 100,
          report_nm: str = "관리종목") -> str:
    params = {
        "method": "searchDetailsSub", "forward": "details_sub",
        "currentPageSize": str(size), "pageIndex": str(page),
        "orderMode": "1", "orderStat": "D",
        "reportNm": report_nm, "fromDate": frm, "toDate": to,
        **{k: "" for k in REQUIRED_EMPTY},
    }
    req = urllib.request.Request(
        URL, data=urllib.parse.urlencode(params).encode(),
        headers={"User-Agent": UA, "Referer": f"{URL}?method=searchDetailsMain",
                 "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                 "X-Requested-With": "XMLHttpRequest"})
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.read().decode("utf-8", "replace")


def parse(page_html: str) -> list[dict]:
    out = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", page_html, re.S):
        cells = [htmllib.unescape(re.sub(r"\s+", " ", re.sub("<[^>]+>", "", c))).strip()
                 for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S)]
        if len(cells) < 4 or not cells[0].isdigit():
            continue
        stamp = re.match(r"(\d{4})-(\d{2})-(\d{2})", cells[1])
        if not stamp:
            continue
        title = cells[3]
        event = event_of(title)
        reason, distress = reason_of(title)
        # 접수번호는 셀 텍스트가 아니라 링크의 onclick 에 있다 —
        # openDisclsViewer('20230630000781',''). 본문을 받으려면 이게 필요하다.
        acpt = re.search(r"openDisclsViewer\('(\d{8,})'", tr)
        out.append({
            "date": "".join(stamp.groups()),
            "corp_name": cells[2],
            "title": title,
            "acptno": acpt.group(1) if acpt else "",
            "market": cells[4] if len(cells) > 4 else "",
            "event": event,
            "reason": reason,
            "is_distress": "" if distress is None else ("1" if distress else "0"),
        })
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--from", dest="frm", type=int, default=2019)
    p.add_argument("--to", dest="to", type=int, default=2026)
    p.add_argument("--out", type=Path, default=Path("data/kind_admin_history.csv"))
    p.add_argument("--pause", type=float, default=0.25)
    args = p.parse_args(argv)

    seen: set[tuple[str, str, str]] = set()
    rows: list[dict] = []
    for year in range(args.frm, args.to + 1):
        got = 0
        prev_page: list[dict] | None = None
        for page in range(1, 21):
            try:
                page_rows = parse(fetch(f"{year}-01-01", f"{year}-12-31", page))
            except Exception as e:
                print(f"  ! {year} p{page} {type(e).__name__}", file=sys.stderr)
                break
            if not page_rows:
                break
            # 끝을 넘기면 마지막 장이 되풀이돼서 온다. 직전 장과 같으면 멈춘다.
            if prev_page is not None and page_rows == prev_page:
                break
            prev_page = page_rows
            for r in page_rows:
                key = (r["date"], r["corp_name"], r["title"])
                if key in seen:
                    continue
                seen.add(key)
                rows.append({"date": r["date"], "corp_name": r["corp_name"],
                             "acptno": r.get("acptno", ""), "title": r["title"],
                             "market": r["market"], "event": r["event"],
                             "reason": r["reason"], "is_distress": r["is_distress"]})
                got += 1
            if len(page_rows) < 100:
                break
            time.sleep(args.pause)
        print(f"  {year}  {got:>4}건", file=sys.stderr)
        time.sleep(args.pause)

    rows.sort(key=lambda r: (r["date"], r["corp_name"]))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["date", "corp_name", "acptno", "title",
                                           "market", "event", "reason", "is_distress"])
        w.writeheader()
        w.writerows(rows)

    from collections import Counter
    ev = Counter(r["event"] for r in rows)
    print(f"\n{len(rows):,}건 → {args.out}", file=sys.stderr)
    print("  사건:", dict(ev.most_common()), file=sys.stderr)
    new = [r for r in rows if r["event"] == "지정"]
    rs = Counter(r["reason"] for r in new)
    print(f"  신규 지정 {len(new):,}건 사유:", dict(rs.most_common()), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
