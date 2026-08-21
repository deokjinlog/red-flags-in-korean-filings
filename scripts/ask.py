"""질문 → 그래프 검색 → 근거 묶음. GraphRAG 의 **검색** 쪽.

왜 검색이 중요한 쪽인가:
  생성은 프롬프트 하나 차이고 환각 차단은 `structure/interpret.py` 가 이미 한다.
  반면 "무엇을 가져올 것인가" 는 그래프가 없으면 아예 불가능하다 — 벡터 유사도로는
  "태영건설과 2홉으로 얽힌 회사" 를 못 찾는다. 그건 구조를 타야 나온다.

무엇을 하나:
  1. 질문에서 기업명을 찾아 corp_code 로 해소
  2. 그 회사를 중심으로 **구조를 타고** 이웃·공동의존점·고리를 모은다
  3. 모은 근거와 허용 토큰을 낸다 — 모델은 이 안에서만 말할 수 있다

사용:
    uv run python scripts/ask.py "태영건설이 흔들리면 어디가 위험해?"
    uv run python scripts/ask.py "케이씨씨는 어느 그룹과 얽혀 있어?" --hops 2
"""
from __future__ import annotations

import argparse, json, sys
from collections import deque
from pathlib import Path

from dartweave.screen.flags import is_adopted, screen
from dartweave.screen.inputs import load_financials
from dartweave.structure.interpret import allowed_tokens, build_prompt
from dartweave.structure.project import project

MIN_NAME = 2


def find_companies(question: str, names: dict[str, str]) -> list[tuple[str, str]]:
    """질문에 등장하는 기업명을 찾는다. 긴 이름부터 봐야 '한화' 가 '한화솔루션' 을 가린다."""
    hits: list[tuple[str, str]] = []
    used = question
    for nm in sorted(names, key=len, reverse=True):
        if len(nm) >= MIN_NAME and nm in used:
            hits.append((nm, names[nm]))
            used = used.replace(nm, " " * len(nm))   # 겹침 방지
    return hits


def neighbors(edges, code, hops):
    """무방향 n-홉. 위험은 출자 방향을 안 가린다."""
    und = {}
    for a, b, _ in edges:
        und.setdefault(a, set()).add(b)
        und.setdefault(b, set()).add(a)
    dist, q = {code: 0}, deque([code])
    while q:
        cur = q.popleft()
        if dist[cur] >= hops:
            continue
        for nx in und.get(cur, ()):
            if nx not in dist:
                dist[nx] = dist[cur] + 1
                q.append(nx)
    dist.pop(code, None)
    return dist


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("question")
    p.add_argument("--hops", type=int, default=2)
    p.add_argument("--graph", default="data/graph_listed.json")
    p.add_argument("--top", type=int, default=10)
    args = p.parse_args(argv)

    names = {v: k for k, v in json.loads(
        Path("data/corpcode.json").read_text(encoding="utf-8")).items()}
    by_name = {v: k for k, v in names.items()}
    raw = json.loads(Path(args.graph).read_text(encoding="utf-8"))["edges"]
    edges = [(a, b, "MAJOR_SHAREHOLDER_OF") for a, b, _ in raw]
    in_graph = {v for e in edges for v in e[:2]}
    nm = lambda c: names.get(c, c)

    # 검정을 통과한 다섯 신호는 재무에서 나온다. 이걸 안 실으면 "사도 되나" 라는
    # 질문에 **떨어진 것만 답하고 통과한 건 빼놓는** 셈이 된다. 실제로 그런 적이 있다.
    load = lambda p: (json.loads(Path(p).read_text(encoding="utf-8"))
                      if Path(p).exists() else {})
    members = set(load("data/conglomerate_members.json").get("members", []))
    baseline = load("data/baseline_graph.json")

    print(f"\n질문  {args.question}")
    found = [(n, c) for n, c in find_companies(args.question, by_name) if c in in_graph]
    if not found:
        print("\n질문에서 그래프에 있는 기업을 못 찾았습니다.")
        print(f"(그래프에는 {len(in_graph):,}개사만 있습니다 — 중소형주는 대부분 없습니다)")
        return 3
    print(f"인식  {', '.join(f'{n}({c})' for n, c in found)}")

    g = project(edges, undirected=True); g.simplify()
    ranked = sorted(zip(g.vs["corp_code"], g.betweenness()), key=lambda x: -x[1])
    choke = {c: i + 1 for i, (c, _) in enumerate(ranked[:12])}

    payload = {"question": args.question, "companies": []}
    for name_, code in found:
        d = neighbors(edges, code, args.hops)
        direct = sorted([c for c, h in d.items() if h == 1],
                        key=lambda c: -g.degree(g.vs.find(corp_code=c).index))
        shared = sorted(((nm(c), h, choke[c]) for c, h in d.items() if c in choke),
                        key=lambda x: (x[1], x[2]))
        fin = load_financials(code)
        flags = screen(edges, code, name=nm, chokepoints=choke, baseline=baseline,
                       conglomerate_members=members,
                       retained_earnings=fin.retained_earnings,
                       operating_income=fin.operating_income,
                       net_income=fin.net_income,
                       operating_cashflow=fin.operating_cashflow,
                       interest_cost=fin.interest_cost,
                       fiscal_year=fin.fiscal_year)
        # 채택된 것부터 낸다 — 순서가 곧 "무엇을 믿고 말할 수 있는가" 다.
        flags.sort(key=lambda f: not is_adopted(f.kind))
        entry = {
            "name": name_,
            "reach": {f"{h}홉": sum(1 for v in d.values() if v == h)
                      for h in range(1, args.hops + 1)},
            "direct": [nm(c) for c in direct[: args.top]],
            "shared_chokepoints": [f"{n} {h}홉 매개{r}위" for n, h, r in shared[:5]],
            "flags": [{"kind": f.kind, "summary": f.summary, "evidence": f.evidence}
                      for f in flags],
        }
        payload["companies"].append(entry)

        print(f"\n── {name_} ──")
        print(f"  도달 범위   {' · '.join(f'{k} {v}개사' for k, v in entry['reach'].items())}")
        print(f"  직접 연결   {', '.join(entry['direct'][:8])}")
        if shared:
            print(f"  공동의존점  {' · '.join(entry['shared_chokepoints'][:3])}")
        adopted = [f for f in flags if is_adopted(f.kind)]
        rest = [f for f in flags if not is_adopted(f.kind)]
        if adopted:
            print(f"\n  ── 검정 통과 ({len(adopted)}건 · 부실과의 연관이 확인된 것만) ──")
            for f in adopted:
                print(f"  [{f.kind}] {f.summary}")
                for line in f.evidence[:2]:
                    print(f"      {line}")
        if rest:
            print("\n  ── 걸렸지만 검정 미통과 (참고) ──")
            for f in rest:
                print(f"  [{f.kind}] {f.summary}")
        if not adopted:
            print("\n  ── 검정 통과한 항목 없음 ──")
            print("  채택된 재무 신호 다섯 개에 하나도 안 걸렸다는 뜻이다. "
                  "'안전' 이 아니라 '이 검사에는 안 걸림' 이다.")

    blob = json.dumps(payload, ensure_ascii=False)
    print(f"\n── 모델에 넘길 것 ──")
    print(f"  근거 {len(blob):,}자 · 허용 토큰 {len(allowed_tokens(blob)):,}개")
    print("  이 토큰 밖의 숫자·기업명이 답변에 나오면 HallucinationDetected 로 중단됩니다.")
    Path("data/last_ask.json").write_text(
        json.dumps({"prompt": build_prompt(blob), "payload": payload},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    print("  → data/last_ask.json (프롬프트 전문)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
