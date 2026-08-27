"""관심 종목 감시 — **새로 뜬 경고만** 알린다.

왜 루프인가:
  "뭘 봐야 하는지" 는 물어보면 답이 나온다. 챗봇이 이미 잘한다. 물어보지 않은
  날에 알려주는 것만 시스템이 필요하다 — 상장사 전수를 계속 들고 있어야 하고,
  같은 신호가 걸렸던 회사들이 실제로 어떻게 됐는지 실측값이 있어야 한다.

왜 "새로 뜬 것만" 인가:
  같은 경고를 매일 다시 띄우면 사람이 읽기를 멈춘다. 그러면 진짜 새 경고가 떠도
  묻힌다. 이미 알린 신호는 `data/watch_state.json` 에 적어 두고 건너뛴다.

⚠️ 이 스크립트는 스스로 돌지 않는다. 사람이 실행하거나 스케줄러가 부른다.

사용:
    uv run python scripts/watch.py --add 풍원정밀 --add 케이씨씨
    uv run python scripts/watch.py                    # 새 경고만
    uv run python scripts/watch.py --all              # 이미 알린 것도 다시
    uv run python scripts/watch.py --out data/alerts.html
"""
from __future__ import annotations

import argparse
import html
import json
from pathlib import Path

from dartweave.screen.alert import BLIND_SPOTS, Alert, build
from dartweave.screen.audit import (
    has_going_concern,
    normalize_opinion,
    rows_for_year,
)

WATCHLIST = Path("data/watchlist.json")
STATE = Path("data/watch_state.json")


def _read(path: str | Path) -> dict:
    p = Path(path)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def audit_alerts(records: list[dict], year: int) -> list[Alert]:
    """감사보고서에서 나오는 경고. 의견과 강조사항은 **다른 신호**다.

    의견거절이면 계속기업 경고를 따로 내지 않는다 — 같은 사실을 두 번 세면
    걸린 개수가 부풀고, 개수는 사람이 심각도로 읽는다.
    """
    rows = rows_for_year(records, year)
    if not rows:
        return []
    adverse = [r for r in rows if normalize_opinion(r.get("opinion")).is_adverse]
    concern = [r for r in rows if has_going_concern(r.get("emphasis"))]
    if adverse:
        op = normalize_opinion(adverse[0].get("opinion")).value
        return [a for a in [build("의견거절·한정",
                                  f"{year} 사업연도 감사의견 **{op}**")] if a]
    if concern:
        kind = "적정인데 계속기업 경고"
        return [a for a in [build(
            kind, f"{year} 사업연도 감사의견은 적정인데, 강조사항에 "
                  f"계속기업 불확실성이 적혀 있습니다")] if a]
    return []


def financial_alerts(fin: dict, code: str, year: str) -> list[Alert]:
    v = (fin.get(year) or {}).get(code) or {}
    r = v.get("이익잉여금")
    if r is None or float(r) >= 0:
        return []
    a = build("결손금", f"{year}년 이익잉여금이 마이너스 — 누적 결손 "
                     f"{abs(float(r)) / 1e8:,.0f}억")
    return [a] if a else []


def alerts_for(code: str, *, audits: dict, fin: dict, year: int) -> list[Alert]:
    return (audit_alerts(audits.get(code) or [], year)
            + financial_alerts(fin, code, str(year)))


def render(name: str, code: str, alerts: list[Alert]) -> str:
    if not alerts:
        return f"  {name}({code}) — 새 경고 없음"
    out = [f"\n  ■ {name}({code}) — 새 경고 {len(alerts)}건"]
    for a in alerts:
        out.append(f"    · {a.kind}: {a.found}")
        out.append(f"      {a.evidence.sentence()}")
        out.append(f"      {a.evidence.caveat()}")
        out.append(f"      원문: {a.where}")
        out.append(f"      풀리는 조건: {a.refutes}")
        out.append(f"      근거: {a.evidence.provenance()}")
    return "\n".join(out).replace("**", "")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--add", action="append", default=[], help="관심 종목 추가 (회사명)")
    p.add_argument("--remove", action="append", default=[])
    p.add_argument("--year", type=int, default=2023, help="판정에 쓸 사업연도")
    p.add_argument("--all", action="store_true", help="이미 알린 것도 다시 낸다")
    p.add_argument("--out", default=None, help="HTML 카드로 저장")
    args = p.parse_args(argv)

    names = _read("data/corpcode.json")            # 이름 → 코드
    watch = _read(WATCHLIST) or {}

    for n in args.add:
        code = names.get(n)
        if not code:
            print(f"  '{n}' 을 찾지 못했습니다 — 정식 회사명이어야 합니다")
            continue
        watch[code] = n
    for n in args.remove:
        watch.pop(names.get(n, n), None)
    if args.add or args.remove:
        # 등록은 설정이고 감시는 실행이다. 여기서 판정까지 해 버리면 그 경고가
        # "이미 알린 것" 으로 기록돼서, 정작 다음 실행 때 안 나온다.
        WATCHLIST.parent.mkdir(parents=True, exist_ok=True)
        WATCHLIST.write_text(json.dumps(watch, ensure_ascii=False, indent=1),
                             encoding="utf-8")
        print(f"관심 종목 {len(watch)}곳 — 인자 없이 다시 실행하면 경고를 냅니다")
        return 0

    if not watch:
        print("관심 종목이 없습니다 — --add 회사명 으로 추가하세요")
        return 0

    audits = _read("data/audit_opinions.json")
    fin = _read("data/fin_by_year.json")
    state = {} if args.all else _read(STATE)

    fired: list[tuple[str, str, list[Alert]]] = []
    new_state = dict(state)
    for code, name in watch.items():
        found = alerts_for(code, audits=audits, fin=fin, year=args.year)
        seen = set(state.get(code, []))
        fresh = [a for a in found if f"{args.year}:{a.kind}" not in seen]
        new_state[code] = sorted({f"{args.year}:{a.kind}" for a in found} | seen)
        fired.append((name, code, fresh))

    total = sum(len(f) for _, _, f in fired)
    print(f"관심 종목 {len(watch)}곳 · {args.year} 사업연도 기준 · 새 경고 {total}건")
    for name, code, fresh in fired:
        print(render(name, code, fresh))
    print("\n  이 감시가 보지 않는 것")
    for b in BLIND_SPOTS:
        print(f"    · {b.replace('**', '')}")

    STATE.write_text(json.dumps(new_state, ensure_ascii=False, indent=1),
                     encoding="utf-8")
    if args.out:
        Path(args.out).write_text(_html(fired), encoding="utf-8")
        print(f"\n→ {args.out}")
    return 0


def _html(fired: list[tuple[str, str, list[Alert]]]) -> str:
    def rich(t: str) -> str:
        out, parts = "", html.escape(t).split("**")
        for i, x in enumerate(parts):
            out += f"<b>{x}</b>" if i % 2 else x
        return out

    cards = ""
    for name, code, alerts in fired:
        if not alerts:
            continue
        for a in alerts:
            link = (f'<a href="{a.url}" target="_blank" rel="noopener">원문 공시</a>'
                    if a.url else "")
            cards += (
                f'<article><div class="k">{html.escape(a.kind)}</div>'
                f'<h3>{html.escape(name)} · {rich(a.found)}</h3>'
                f'<p class="what">{rich(a.what)}</p>'
                f'<p class="ev">{rich(a.evidence.sentence())}</p>'
                f'<p class="cav">{rich(a.evidence.caveat())}</p>'
                f'<div class="meta"><span>{html.escape(a.where)}</span>'
                f'<span>풀리는 조건 — {html.escape(a.refutes)}</span>'
                f'<span>{rich(a.evidence.provenance())}</span>{link}</div></article>')
    blind = "".join(f"<li>{rich(b)}</li>" for b in BLIND_SPOTS)
    return f"""<title>새 경고</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans+KR:wght@400;500;600&family=Noto+Serif+KR:wght@700&display=swap">
<style>
:root{{--ground:#F2F4F1;--sheet:#fff;--sunk:#E7EBE6;--ink:#1A211C;--ink-2:#545C55;
--ink-3:#8A928B;--rule:#D4D9D3;--alarm:#8A3A1E;--verified:#1F4D3F;
--serif:"Noto Serif KR",serif;--sans:"IBM Plex Sans KR",system-ui,sans-serif;
--mono:"IBM Plex Mono",monospace}}
@media(prefers-color-scheme:dark){{:root:not([data-theme="light"]){{
--ground:#101410;--sheet:#181D18;--sunk:#212721;--ink:#E4E9E3;--ink-2:#A3ABA2;
--ink-3:#788077;--rule:#2A312A;--alarm:#DE9268;--verified:#7FBFA3}}}}
:root[data-theme="dark"]{{--ground:#101410;--sheet:#181D18;--sunk:#212721;
--ink:#E4E9E3;--ink-2:#A3ABA2;--ink-3:#788077;--rule:#2A312A;--alarm:#DE9268;
--verified:#7FBFA3}}
*{{box-sizing:border-box}}
body{{background:var(--ground);color:var(--ink);font-family:var(--sans);margin:0;
line-height:1.75;font-size:16px}}
.wrap{{max-width:42rem;margin:0 auto;padding:3rem 1.3rem 5rem;
display:flex;flex-direction:column;gap:1rem}}
h1{{font-family:var(--serif);font-size:1.9rem;margin:0 0 1.4rem;line-height:1.3}}
article{{background:var(--sheet);border:1px solid var(--rule);border-radius:2px;
padding:1.1rem 1.25rem;border-left:3px solid var(--alarm);
display:flex;flex-direction:column;gap:.45rem}}
.k{{font-family:var(--mono);font-size:.68rem;letter-spacing:.11em;
color:var(--alarm);font-weight:600}}
article h3{{font-size:1.02rem;margin:0;font-weight:600;line-height:1.55}}
article p{{margin:0;font-size:.92rem;color:var(--ink-2)}}
.what{{padding-left:.7rem;border-left:2px solid var(--rule)}}
.ev b{{color:var(--alarm)}}
.cav{{color:var(--ink-3);font-size:.88rem}}
.cav b{{color:var(--ink-2)}}
.meta{{display:flex;flex-direction:column;gap:.15rem;font-family:var(--mono);
font-size:.7rem;color:var(--ink-3);border-top:1px solid var(--rule);
padding-top:.5rem;margin-top:.15rem}}
.meta b{{color:var(--ink-2)}}
.blind{{background:var(--sunk);border:1px solid var(--rule);border-radius:2px;
padding:1rem 1.2rem;margin-top:1rem}}
.blind h2{{font-family:var(--mono);font-size:.7rem;letter-spacing:.12em;
color:var(--ink-3);margin:0 0 .5rem;font-weight:600}}
.blind ul{{margin:0;padding-left:1.1rem;color:var(--ink-2);font-size:.9rem}}
.blind b{{color:var(--ink)}}
article b{{color:var(--ink)}}
</style>
<div class="wrap">
<h1>새 경고</h1>
{cards or '<p>새 경고가 없습니다.</p>'}
<div class="blind"><h2>이 감시가 보지 않는 것</h2><ul>{blind}</ul></div>
</div>"""


if __name__ == "__main__":
    raise SystemExit(main())
