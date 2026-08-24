"""종목 하나의 "사지 말 이유" 체크리스트를 HTML 로 낸다.

무엇을 내나:
  판정이 아니라 **위치**다 — 채택된 신호 몇 개에 걸렸고, 그 구간의 실측 부실률이
  얼마인가. 그리고 항목마다 "이 검사에 걸린 회사 100곳 중 몇 곳이 실제로 2년 안에
  부실이 났는가" 가 붙는다. 교과서 기준선이 아니라 우리가 잰 값이다.

무엇을 안 내나:
  점수·등급·매수매도. 걸린 것의 90%는 2년 안에 아무 일도 없었고, 그걸 알면서
  "위험" 이라고 쓰면 거짓말이다.

  그리고 **우리가 못 본 것**을 반드시 싣는다. 주석·담보·소송·조항 본문은 안 읽는다.
  안 적으면 읽는 사람이 "체크리스트를 통과했으니 괜찮다" 로 읽는다.

사용:
    uv run python scripts/report_company.py --name 풍원정밀
    uv run python scripts/report_company.py --name 삼부토건 --out docs/report.html
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path

from dartweave.screen.checklist import (
    NOT_CHECKED,
    READING_ORDER,
    WHERE_IN_DART,
    WHERE_TO_READ,
    build,
    evidence_of,
    what_it_is,
)
from dartweave.screen.distribution import position, trend
from dartweave.screen.sector import MIN_PEERS, is_shell, name_of, sector_of
from dartweave.dart.live import neighbours
from dartweave.parse.notes import worth_reading
from dartweave.screen.flags import ADOPTED_KINDS, screen
from dartweave.structure.project import project
from dartweave.screen.inputs import load_financials

_BOLD = re.compile(r"\*\*(.+?)\*\*")


def rich(text: str) -> str:
    """`**강조**` 만 살리고 나머지는 이스케이프한다. 원문이 HTML 을 만들지 않게."""
    return _BOLD.sub(r"<b>\1</b>", html.escape(text))


def known_map(fin, bond_count: int | None) -> dict[str, bool | None]:
    """채택 신호별로 판정 가능 여부. **모르는 걸 False 로 세지 않는다.**"""
    def neg(v):
        return None if v is None else v < 0
    return {
        "결손금": neg(fin.retained_earnings),
        "영업손실": neg(fin.operating_income),
        "당기순손실": neg(fin.net_income),
        "영업현금흐름 음수": neg(fin.operating_cashflow),
        "이자보상배율 1 미만": (
            None if fin.operating_income is None or not fin.interest_cost
            else fin.operating_income < fin.interest_cost),
        "최근 3년 CB·BW 발행": None if bond_count is None else bond_count >= 1,
        "최근 3년 CB·BW 2회 이상": None if bond_count is None else bond_count >= 2,
        "최대주주 변경 최근 3년": None,      # 별도 수집분이 있어야 판정한다
    }


def render(c, extra: dict) -> str:
    """확신의 사다리를 그대로 문서 구조로 쓴다.

    위험도 색(빨강·노랑·초록)을 쓰지 않는다. 그건 "우리가 위험을 판정한다" 는 뜻인데
    우리는 안 한다. 대신 **얼마나 아는가**를 왼쪽 레일의 굵기로 표시한다 —
    잰 것(실선) / 검정 실패(파선) / 아예 못 본 것(점선).
    """
    context = extra.pop("_context", {})

    def card(flag, rail):
        lines, verdict = evidence_of(flag)
        body = "".join(f"<p>{rich(x)}</p>" for x in lines)
        what = what_it_is(flag.kind)
        what = f'<p class="what">{rich(what)}</p>' if what else ""
        ctx = context.get(flag.kind)
        meta = ""
        if ctx:
            bits = []
            if ctx.get("place"):
                bits.append(f'<span class="where">{rich(ctx["place"])}</span>')
            if ctx.get("peer"):
                bits.append(f'<span class="peer">{rich(ctx["peer"])}</span>')
            if ctx.get("trend"):
                bits.append(f'<span class="trend">{html.escape(ctx["trend"])}</span>')
            if bits:
                meta += f'<div class="meta">{"".join(bits)}</div>'
            if ctx.get("path"):
                meta += f'<div class="path">{html.escape(ctx["path"])}</div>'
        return (f'<article class="item {rail}">'
                f'<div class="kind">{html.escape(flag.kind)}</div>'
                f'<h3>{rich(flag.summary)}</h3>{what}{meta}{body}'
                f'<div class="verdict">{rich(verdict)}</div></article>')

    steps = "".join(
        f'<div class="step"><div class="sn">{html.escape(n)}</div>'
        f'<div class="sb"><div class="st">{html.escape(t)}</div>'
        f"<p>{rich(d)}</p></div></div>"
        for n, t, d in READING_ORDER)
    moving = drift_line(c, context)
    fired = "".join(card(f, "measured") for f in c.fired) or         '<p class="none">채택된 신호에 걸린 항목이 없습니다.</p>'
    ref = "".join(card(f, "failed") for f in c.reference) or '<p class="none">없음</p>'
    clear = "".join(f"<li>{html.escape(k)}</li>" for k in c.clear) or "<li>없음</li>"
    unknown = "".join(f"<li>{html.escape(k)}</li>" for k in c.unknown) or "<li>없음</li>"
    notchk = "".join(f'<div class="unread"><div class="t">{html.escape(t)}</div>'
                     f"<p>{html.escape(d)}</p></div>" for t, d in NOT_CHECKED)
    notes = extra.pop("_notes", [])
    if notes:
        where = "".join(
            f"<tr><td class='t'>주석 {html.escape(n.number)}. "
            f"{html.escape(n.title)}</td><td>{html.escape(n.why)}</td></tr>"
            for n in notes)
    else:
        where = "".join(f"<tr><td class='t'>{html.escape(t)}</td>"
                        f"<td class='path'>{html.escape(d)}</td></tr>"
                        for t, d in WHERE_TO_READ)
    facts = "".join(f"<tr><td class='t'>{html.escape(k)}</td>"
                    f"<td class='num'>{html.escape(v)}</td></tr>"
                    for k, v in extra.items())

    return f"""<title>{html.escape(c.name)} 공시 점검표</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans+KR:wght@400;500;600&family=Noto+Serif+KR:wght@600;700&display=swap">
<style>
:root{{
  --ground:#F2F4F1; --sheet:#FFFFFF; --sunk:#E7EBE6;
  --ink:#1A211C; --ink-2:#545C55; --ink-3:#8A928B;
  --rule:#D4D9D3; --rule-2:#B6BEB5;
  --verified:#1F4D3F;          /* 잰 것 — 원장 초록 */
  --rate:#8A3A1E;              /* 실측 수치에만 쓴다 */
  --serif:"Noto Serif KR",Batang,Georgia,serif;
  --sans:"IBM Plex Sans KR","Apple SD Gothic Neo","Malgun Gothic",system-ui,sans-serif;
  --mono:"IBM Plex Mono",Consolas,ui-monospace,monospace;
}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{
  --ground:#101410; --sheet:#181D18; --sunk:#212721;
  --ink:#E4E9E3; --ink-2:#A3ABA2; --ink-3:#788077;
  --rule:#2A312A; --rule-2:#3E463D;
  --verified:#7FBFA3; --rate:#DE9268;
}}}}
:root[data-theme="dark"]{{
  --ground:#101410; --sheet:#181D18; --sunk:#212721;
  --ink:#E4E9E3; --ink-2:#A3ABA2; --ink-3:#788077;
  --rule:#2A312A; --rule-2:#3E463D;
  --verified:#7FBFA3; --rate:#DE9268;
}}

*{{box-sizing:border-box}}
body{{background:var(--ground);color:var(--ink);font-family:var(--sans);
  font-size:16px;line-height:1.75;margin:0;-webkit-font-smoothing:antialiased}}
.wrap{{max-width:44rem;margin:0 auto;padding:3.5rem 1.4rem 6rem;
  display:flex;flex-direction:column;gap:3.4rem}}

header{{display:flex;flex-direction:column;gap:.7rem;
  padding-bottom:1.5rem;border-bottom:1px solid var(--rule-2)}}
.stamp{{font-family:var(--mono);font-size:.68rem;letter-spacing:.16em;
  text-transform:uppercase;color:var(--verified);font-weight:600}}
h1{{font-family:var(--serif);font-weight:700;font-size:clamp(1.7rem,4.4vw,2.5rem);
  line-height:1.25;letter-spacing:-.015em;margin:0;text-wrap:balance}}
.lede{{margin:0;color:var(--ink-2);font-size:1rem;max-width:62ch}}

section{{display:flex;flex-direction:column;gap:1.1rem}}
.head{{display:flex;flex-direction:column;gap:.3rem}}
h2{{font-family:var(--serif);font-weight:700;font-size:1.35rem;line-height:1.35;
  margin:0;text-wrap:balance}}
.sub{{margin:0;color:var(--ink-2);font-size:.94rem;max-width:64ch}}

/* 위치 — 판정이 아니라 어디에 있는가 */
.place{{background:var(--sheet);border:1px solid var(--rule-2);border-radius:2px;
  padding:1.5rem 1.6rem;display:flex;flex-direction:column;gap:.8rem}}
.place .line{{font-family:var(--serif);font-weight:700;font-size:1.18rem;line-height:1.55}}
.place p{{margin:0;color:var(--ink-2);font-size:.95rem}}
.place .drift{{margin-top:.55rem;padding-top:.55rem;border-top:1px solid var(--rule)}}
.item .what{{margin:.1rem 0 .55rem;color:var(--ink-2);font-size:.93rem;line-height:1.75;
  padding-left:.7rem;border-left:2px solid var(--rule-2)}}
.item .what b{{color:var(--ink)}}
.steps{{display:flex;flex-direction:column;border-top:1px solid var(--rule)}}
.step{{display:grid;grid-template-columns:2rem 1fr;gap:.9rem;padding:.85rem .1rem;
  border-bottom:1px solid var(--rule);align-items:start}}
.sn{{font-family:var(--mono);font-size:1.25rem;color:var(--rule-2);line-height:1.2}}
.st{{font-weight:600;font-size:.97rem;margin-bottom:.2rem}}
.step p{{margin:0;color:var(--ink-2);font-size:.93rem;line-height:1.7}}
.step b{{color:var(--ink)}}
.scope p{{margin:0;color:var(--ink-2);font-size:.95rem;line-height:1.75;
  background:var(--sunk);border:1px solid var(--rule);border-radius:2px;padding:.9rem 1rem}}
.scope b{{color:var(--ink)}}
.place b{{color:var(--ink)}}

/* 확신의 레일 — 굵기가 아는 정도다 */
.item{{background:var(--sheet);border:1px solid var(--rule);border-radius:2px;
  padding:1.15rem 1.3rem;display:flex;flex-direction:column;gap:.5rem;position:relative}}
.item::before{{content:"";position:absolute;left:0;top:0;bottom:0;width:3px}}
.item.measured::before{{background:var(--verified)}}
.item.failed::before{{background:repeating-linear-gradient(180deg,
  var(--rule-2) 0 6px,transparent 6px 12px)}}
.kind{{font-family:var(--mono);font-size:.68rem;letter-spacing:.11em;
  color:var(--verified);font-weight:600}}
.item.failed .kind{{color:var(--ink-3)}}
.item h3{{font-family:var(--sans);font-size:1.02rem;font-weight:600;margin:0;line-height:1.55}}
.item p{{margin:0;font-size:.9rem;color:var(--ink-2)}}
.meta{{display:flex;flex-wrap:wrap;gap:.4rem;margin:.1rem 0 .2rem}}
.meta span{{font-family:var(--mono);font-size:.7rem;letter-spacing:.02em;
  padding:.12rem .5rem;border-radius:2px}}
.meta .where{{color:var(--rate);background:var(--sunk)}}
.meta .trend{{color:var(--ink-2);background:var(--sunk)}}
.meta .peer{{color:var(--ink-2);background:var(--sunk)}}
.item .path{{font-family:var(--mono);font-size:.7rem;color:var(--ink-3);
  padding-left:.1rem}}
.verdict{{font-family:var(--mono);font-size:.76rem;line-height:1.7;color:var(--ink-2);
  border-top:1px solid var(--rule);padding-top:.55rem;margin-top:.15rem}}
.item b{{color:var(--ink)}}
.verdict b{{color:var(--rate)}}

.cols{{display:grid;grid-template-columns:repeat(auto-fit,minmax(15rem,1fr));gap:.9rem}}
.col{{background:var(--sheet);border:1px solid var(--rule);border-radius:2px;padding:1.1rem 1.2rem}}
.col h3{{font-family:var(--mono);font-size:.68rem;letter-spacing:.12em;text-transform:uppercase;
  color:var(--ink-3);margin:0 0 .5rem;font-weight:600}}
.col ul{{margin:0;padding-left:1.05rem;color:var(--ink-2);font-size:.92rem}}
.col li{{margin-bottom:.2rem}}

/* 못 본 것 — 점선 레일 */
.unreads{{display:flex;flex-direction:column;gap:.55rem}}
.unread{{border-left:3px dotted var(--rule-2);padding:.35rem 0 .35rem 1rem}}
.unread .t{{font-weight:600;font-size:.95rem}}
.unread p{{margin:0;color:var(--ink-2);font-size:.88rem}}

.tablewrap{{overflow-x:auto;border:1px solid var(--rule);border-radius:2px;background:var(--sheet)}}
table{{border-collapse:collapse;width:100%;min-width:30rem}}
td{{padding:.65rem .95rem;border-bottom:1px solid var(--rule);font-size:.92rem;
  vertical-align:top;color:var(--ink-2)}}
tr:last-child td{{border-bottom:none}}
td.t{{font-weight:600;color:var(--ink);white-space:nowrap;width:11rem}}
td.num{{font-family:var(--mono);font-variant-numeric:tabular-nums;color:var(--rate);
  font-weight:500;text-align:right;white-space:nowrap}}
td.path{{font-family:var(--mono);font-size:.8rem}}
.none{{color:var(--ink-3);font-size:.95rem;margin:0}}

footer{{border-top:1px solid var(--rule);padding-top:1.3rem;color:var(--ink-3);
  font-size:.83rem;line-height:1.75;display:flex;flex-direction:column;gap:.5rem}}
</style>

<div class="wrap">
<header>
  <div class="stamp">DART 자동 점검 · {html.escape(c.corp_code)} · {html.escape(c.fiscal_year)} 사업연도</div>
  <h1>{html.escape(c.name)}<br>사지 말 이유 점검표</h1>
  <p class="lede">판정하지 않습니다. <b>어느 구간에 있는지</b>와 그 구간의 실측 부실률만
     냅니다. 항목마다 붙은 숫자는 교과서 기준선이 아니라 상장사 2,255사 × 기준시점 4개에서
     직접 잰 값입니다.</p>
</header>

<section>
  <div class="place">
    <div class="line">{rich(c.summary)}</div>
    {moving}
    <p>0개 걸린 회사는 <b>1.3~1.5%</b>, 5개 이상은 <b>7.6~10.8%</b> 가 이후 2년 안에
       부도·회생·관리절차·영업정지·상장폐지로 갔습니다. 그래도 <b>걸린 것의 열에 아홉은
       아무 일도 없었습니다</b> — 이건 "위험" 이 아니라 "여기서 멈추고 이유를 찾아보라"
       는 신호입니다.</p>
  </div>
  <div class="tablewrap"><table><tbody>{facts}</tbody></table></div>
</section>

<section class="howto">
  <div class="head"><h2>이 리포트 읽는 법</h2>
    <p class="sub">전부 읽어야 쓸 수 있는 문서는 결국 안 읽힙니다. 어디서 멈춰도
       되는지를 같이 적었습니다.</p></div>
  <div class="steps">{steps}</div>
</section>

<section class="scope">
  <div class="head"><h2>이 점검표가 답하지 않는 것</h2></div>
  <p>여기서 나온 숫자는 <b>사지 말 이유가 있는지</b>에만 답합니다. 살 이유는 다루지
     않습니다 — 주가·PER·목표주가 같은 <b>가격 판단은 아예 넣지 않았고</b>, 수주 잔고,
     신제품, 업황 사이클, 경영진 역량처럼 공시 숫자표 밖에 있는 것도 보지 않습니다.
     그래서 <b>0개 걸림이 매수 신호가 아니고</b>, 5개 걸림도 그 자체로는 매도 신호가
     아닙니다. 걸린 항목은 <b>멈춰서 원문을 열어 볼 자리</b>를 가리킬 뿐입니다.</p>
</section>

<section>
  <div class="head">
    <h2>걸린 항목</h2>
    <p class="sub">기준시점 4개 × 규모·업종 통제 7설정 = 28조합 전부에서 유의했던
       신호만 셉니다.</p>
  </div>
  {fired}
</section>

<section>
  <div class="head">
    <h2>안 걸린 것과 못 잰 것</h2>
    <p class="sub">"0개 걸림" 이 안전을 뜻하려면 <b>못 잰 게 없어야</b> 합니다.
       재무를 못 받은 항목은 통과가 아니라 미상입니다.</p>
  </div>
  <div class="cols">
    <div class="col"><h3>통과</h3><ul>{clear}</ul></div>
    <div class="col"><h3>판정 못 함</h3><ul>{unknown}</ul></div>
  </div>
</section>

<section>
  <div class="head">
    <h2>참고 — 검정을 통과하지 못한 항목</h2>
    <p class="sub">걸리긴 했는데 이 신호가 실제로 부실을 가른다는 근거가 없습니다.
       통제하면 사라지거나, 방향이 반대이거나, 표본이 모자랍니다.</p>
  </div>
  {ref}
</section>

<section>
  <div class="head">
    <h2>확인하지 못한 것</h2>
    <p class="sub">아래는 <b>읽지 않았습니다.</b> 점검표를 통과했다고 괜찮다는 뜻이
       아닙니다 — 진짜 위험은 대개 이쪽에 숨습니다.</p>
  </div>
  <div class="unreads">{notchk}</div>
</section>

<section>
  <div class="head">
    <h2>다음에 사람이 읽을 곳</h2>
    <p class="sub">주석은 우리가 <b>읽지 않습니다</b> — 표가 전치되고 다층이라
       결정적으로 못 뽑고, 대조할 정답지가 없어 추출 품질도 못 잽니다. 대신 7백만 자
       중 <b>어디를 볼지</b>는 정확히 짚어드립니다.</p>
  </div>
  <div class="tablewrap"><table><tbody>{where}</tbody></table></div>
</section>

<footer>
  <div>출처 — DART OpenAPI 정기보고서 · 주요사항보고서 · 공정거래위원회 공시 · KRX KIND.
       원문 추출은 타법인 출자현황 대조에서 재현율 100% · 정밀도 100%.</div>
  <div>투자자문이 아닙니다. 점수도 등급도 매기지 않으며, 걸린 항목과 그 항목의 실측
       부실률만 냅니다. 최종 판단과 책임은 투자자 본인에게 있습니다.</div>
</footer>
</div>
"""


# 신호 → (어느 파일의 어느 계정, 높을수록 나쁜가). 분포 위치를 낼 때 쓴다.
METRIC_OF: dict[str, tuple[str, str, bool]] = {
    "결손금": ("fin", "이익잉여금", False),
    "영업손실": ("fin", "영업이익", False),
    "당기순손실": ("fin", "당기순이익(손실)", False),
    "영업현금흐름 음수": ("cash", "영업활동현금흐름", False),
}


def build_context(code: str, year: str) -> dict[str, dict]:
    """신호마다 분포 위치·추세·DART 경로를 붙인다.

    분포는 **같은 해 상장사 전수**에서 잰다. 임의 임계 대신 실측 위치를 쓰는 건
    루브릭에서 이미 하던 방식이고, 여기서는 재무로 옮긴 것뿐이다.

    전수 위치만으로는 모자란 데가 있다. 조선·건설은 영업현금흐름이 음수인 해가
    흔하고 제약은 영업손실이 흔하다 — 같은 숫자가 업종에 따라 다른 뜻이다. 그래서
    **업종 내 위치**를 나란히 낸다. 업종 표본이 `MIN_PEERS` 미만이면 내지 않는다.
    """
    read = lambda f: (json.loads(Path(f).read_text(encoding="utf-8"))  # noqa: E731
                      if Path(f).exists() else {})
    store = {"fin": read("data/fin_by_year.json"),
             "cash": read("data/cashflow_by_year.json")}
    industry = read("data/industry.json")
    mine_sector = sector_of(industry.get(code))
    named = {v: k for k, v in read("data/corpcode.json").items()}
    shell = {c for c in named if is_shell(named[c])}
    years = [str(int(year) - k) for k in (3, 2, 1, 0)] if year.isdigit() else []

    out: dict[str, dict] = {}
    for kind, path in WHERE_IN_DART.items():
        out[kind] = {"path": path}
    for kind, (which, account, worse_high) in METRIC_OF.items():
        book = store[which]
        mine = (book.get(year, {}).get(code) or {}).get(account)
        if mine is None:
            continue
        others = [float(v[account]) for c, v in book.get(year, {}).items()
                  if v.get(account) is not None and c not in shell]
        pos = position(float(mine), others, higher_is_worse=worse_high)
        if pos:
            out[kind]["place"] = pos.label
        if mine_sector:
            peers = [float(v[account])
                     for c, v in book.get(year, {}).items()
                     if v.get(account) is not None and c not in shell
                     and sector_of(industry.get(c)) == mine_sector]
            ppos = position(float(mine), peers, higher_is_worse=worse_high,
                            min_sample=MIN_PEERS)
            if ppos:
                out[kind]["peer"] = ppos.describe(
                    f"{name_of(mine_sector)} {ppos.sample}사")
        if years:
            t = trend(book, code, account, years, higher_is_worse=worse_high)
            out[kind]["trend"] = f"{t.arrow()} · 억원 {t.as_row()}"
    return out


def drift_line(c, context: dict[str, dict]) -> str:
    """걸린 항목이 **나빠지는 중인지 나아지는 중인지** 를 한 줄로 센다.

    같은 5 개가 걸려도 전부 개선 중인 회사와 전부 악화 중인 회사는 다른 이야기다.
    카드마다 추세를 달아 놨지만 다섯 장을 다 읽어야 보이면 결론에 반영되지 않는다.

    추세를 못 잰 항목은 세지 않는다 — 분모를 아는 것만으로 잡아야 비율이 안 뜬다.
    """
    worse = better = flat = 0
    for f in c.fired:
        arrow = (context.get(f.kind) or {}).get("trend", "")
        if arrow.startswith("악화"):
            worse += 1
        elif arrow.startswith("개선"):
            better += 1
        elif arrow.startswith("거의"):
            flat += 1
    known = worse + better + flat
    if not known:
        return ""
    bits = [f"<b>{worse}개가 3년째 나빠지는 중</b>" if worse else "",
            f"{better}개는 나아지는 중" if better else "",
            f"{flat}개는 그대로" if flat else ""]
    body = " · ".join(b for b in bits if b)
    scope = (f"걸린 {len(c.fired)}개 중 추세를 잴 수 있는 {known}개"
             if known < len(c.fired) else f"걸린 {known}개 전부")
    tail = ("최근 3 년 방향은 걸렸다는 사실만큼이나 중요합니다 — "
            "같은 개수가 걸려도 나아지는 중인 회사와는 다른 이야기입니다.")
    return f'<p class="drift">{scope}: {body}. {tail}</p>'


def rank_chokepoints(edges, top: int = 12) -> dict[str, int]:
    """매개중심성 상위 — 끊으면 여러 묶음이 갈라지는 지점."""
    g = project(edges, undirected=True)
    g.simplify()
    ordered = sorted(zip(g.vs["corp_code"], g.betweenness()), key=lambda x: -x[1])
    return {c: i + 1 for i, (c, _) in enumerate(ordered[:top])}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--name", required=True)
    p.add_argument("--graph", default="data/graph_listed.json")
    p.add_argument("--out", default="")
    p.add_argument("--body", default="",
                   help="원문 XML 경로. 주면 그 회사의 실제 주석 번호를 짚어준다")
    p.add_argument("--live", action="store_true",
                   help="그 회사 최신 원문을 지금 받아 주석 번호를 짚는다(캐시 일주일)")
    p.add_argument("--hops", type=int, default=1,
                   help="지분으로 엮인 이웃을 몇 홉까지 집계할지")
    args = p.parse_args(argv)

    names = json.loads(Path("data/corpcode.json").read_text(encoding="utf-8"))
    code = names.get(args.name)
    if not code:
        print(f"'{args.name}' 을 corpCode 에서 찾지 못했습니다.", file=sys.stderr)
        return 2

    raw = json.loads(Path(args.graph).read_text(encoding="utf-8"))["edges"]
    edges = [(a, b, "MAJOR_SHAREHOLDER_OF") for a, b, _ in raw]
    nm = {v: k for k, v in names.items()}
    fin = load_financials(code)

    # ⚠️ 검정용과 조회용은 창이 다르다.
    #   검정  기준시점 T 이전 3년 — T 이후를 세면 미래를 훔쳐본다
    #   조회  **오늘 기준** 3년 — 지금 이 종목을 보는 게 목적이라 최신이 맞다
    # 같은 규칙을 쓰면 2025년 발행 4건이 "창 밖" 이라고 빠진다. 실제로 그랬다.
    bonds = json.loads(Path("data/bond_filings.json").read_text(encoding="utf-8"))
    latest = max((v.get("date", "") for v in bonds.values()), default="")[:4]
    window = {str(int(latest or fin.fiscal_year or 0) - k) for k in (0, 1, 2)}
    bond_count = sum(1 for v in bonds.values()
                     if v.get("corp_code") == code and v.get("date", "")[:4] in window)

    load = lambda f: (json.loads(Path(f).read_text(encoding="utf-8"))  # noqa: E731
                      if Path(f).exists() else {})
    members = set(load("data/conglomerate_members.json").get("members", []))
    flags = screen(
        edges, code, name=lambda c: nm.get(c, c),
        chokepoints=rank_chokepoints(edges),
        baseline=load("data/baseline_graph.json"),
        conglomerate_members=members,
        retained_earnings=fin.retained_earnings,
        operating_income=fin.operating_income,
        net_income=fin.net_income,
        operating_cashflow=fin.operating_cashflow,
        interest_cost=fin.interest_cost,
        fiscal_year=fin.fiscal_year,
    )
    known = known_map(fin, bond_count if bonds else None)
    # CB 는 screen() 이 안 내므로 여기서 붙인다 — 검정은 통과했지만 도구 검사로는
    # 아직 안 들어가 있다. 개수에는 세고 카드로도 낸다.
    from dartweave.screen.flags import Flag
    if known["최근 3년 CB·BW 발행"]:
        flags.append(Flag(
            kind="최근 3년 CB·BW 2회 이상" if bond_count >= 2 else "최근 3년 CB·BW 발행",
            summary=f"최근 3년({min(window)}~{max(window)}) 전환사채·신주인수권부사채 "
                    f"**{bond_count}회** 발행",
            evidence=["2회 이상인 기업의 이후 2년 부실률 실측 7.5~10.3% "
                      "(규모·업종 통제 후 ×2.5~6.7 · 기준시점 4개)",
                      "└ **채택** · 검정한 24종 중 가장 강한 신호다"]))

    money = lambda v: "미상" if v is None else f"{v / 1e8:,.0f}억"  # noqa: E731
    extra = {
        "기준 사업연도": fin.fiscal_year or "미상",
        "이익잉여금": money(fin.retained_earnings),
        "영업이익": money(fin.operating_income),
        "당기순이익": money(fin.net_income),
        "영업활동현금흐름": money(fin.operating_cashflow),
        "이자비용": money(fin.interest_cost),
        f"CB·BW 발행 ({min(window)}~{max(window)})":
            f"{bond_count}회" if bonds else "미상",
    }
    if args.body and Path(args.body).exists():
        extra["_notes"] = worth_reading(
            Path(args.body).read_text(encoding="utf-8", errors="ignore"))
    elif args.live:
        # 조회용은 batch 가 아니다. 원문 8,878건을 미리 받다가 IP 가 차단됐고,
        # 받고 보니 주석은 정답지가 없어 검정에 못 쓰는 데이터였다.
        from dartweave.config import Settings
        from dartweave.dart.client import DartClient
        from dartweave.dart.live import body_of, latest_report
        client = DartClient(api_key=Settings.from_env().dart_api_key)
        try:
            report = latest_report(client, code)
            if report:
                extra["최신 정기보고서"] = (f"{report.get('report_nm', '')} "
                                    f"({report.get('rcept_dt', '')})")
                extra["_notes"] = worth_reading(body_of(client, report["rcept_no"]))
            else:
                print("  최신 정기보고서를 못 찾았습니다.", file=sys.stderr)
        except Exception as exc:                          # noqa: BLE001
            print(f"  원문 조회 실패 — {exc}", file=sys.stderr)
        finally:
            client.close()

    # 지분으로 엮인 이웃의 재무를 **집계한다**. 예측이 아니라 사실 진술이다 —
    # 우리 검정은 구조 신호가 부실을 예고하지 못한다고 나왔고, 그래서 "위험이
    # 번진다" 고 쓰지 않는다. "엮인 곳 중 몇 곳이 걸렸다" 까지만 센다.
    near = neighbours(edges, code, hops=args.hops)
    if near:
        hit = 0
        for other in near:
            nf = load_financials(other)
            k = known_map(nf, None)
            if any(k[x] for x in ("결손금", "영업손실", "당기순손실",
                                  "영업현금흐름 음수", "이자보상배율 1 미만")):
                hit += 1
        extra[f"지분으로 엮인 곳 ({args.hops}홉)"] = (
            f"{len(near)}곳 · 그중 채택 신호에 걸린 곳 {hit}곳")
    extra["_context"] = build_context(code, fin.fiscal_year or "")
    c = build(args.name, code, fin.fiscal_year or "미상", flags, known)
    out = Path(args.out or f"data/report_{args.name}.html")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(c, extra), encoding="utf-8")
    print(f"{args.name} · {c.summary}")
    print(f"  걸림 {len(c.fired)} · 통과 {len(c.clear)} · 판정 못 함 {len(c.unknown)} "
          f"· 참고 {len(c.reference)}")
    print(f"→ {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
