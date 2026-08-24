"""조회 계층 — 물어볼 때 그 회사 것만 받는다.

왜 두 층으로 가르나:
  용도가 다르면 수집 방식도 달라야 한다. 섞었다가 한 번 크게 틀렸다.

      검정용(batch)   신호가 실제로 가르는지 재려면 2,255사 × 기준시점 4개가 필요하다.
                     한 회사만 봐서는 **기저율을 못 구한다** — "이 구간의 실측 부실률
                     7.6~10.8%" 라는 문장이 나오려면 전수가 있어야 한다.

      조회용(live)    특정 회사의 최신 원문·주석·이웃 재무. 질문마다 다르고 최신이어야
                     한다. 미리 받아둘 이유가 없다.

  **실패로 배운 것:** 원문 8,878건을 batch 로 받다가 IP 가 차단됐고, 받고 나서 보니
  주석은 정답지가 없어 검정에 못 쓰는 데이터였다. 원문은 처음부터 조회용이었다.

캐시를 두는 이유:
  같은 회사를 두 번 물으면 두 번 받을 이유가 없다. 다만 **만료를 둔다** — 조회용의
  값은 최신이라는 데 있고, 캐시가 오래되면 그 값이 사라진다.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

from dartweave.dart.client import DartClient
from dartweave.dart.status import Action, classify

CACHE = Path("data/cache")
DEFAULT_TTL = 60 * 60 * 24 * 7          # 일주일. 정기보고서는 분기마다 바뀐다.


@dataclass(frozen=True)
class Cached:
    path: Path
    ttl: int = DEFAULT_TTL

    @property
    def fresh(self) -> bool:
        return (self.path.exists()
                and time.time() - self.path.stat().st_mtime < self.ttl)


def _slot(kind: str, key: str, ttl: int) -> Cached:
    return Cached(CACHE / kind / f"{key}.json", ttl=ttl)


def latest_report(client: DartClient, corp_code: str, *,
                  ttl: int = DEFAULT_TTL) -> dict | None:
    """가장 최근 정기보고서 한 건(사업·반기·분기). 없으면 None.

    조회용이라 **오늘 기준 최신**을 쓴다. 검정용의 "T 이전" 규칙과 다르다 — 검정은
    미래를 훔쳐보면 안 되지만, 조회는 최신이 아니면 쓸 이유가 없다.
    """
    slot = _slot("report", corp_code, ttl)
    if slot.fresh:
        return json.loads(slot.path.read_text(encoding="utf-8")) or None

    year = time.strftime("%Y")
    payload = client.get_json("list.json", {
        "corp_code": corp_code, "bgn_de": f"{int(year) - 1}0101",
        "end_de": f"{year}1231", "pblntf_ty": "A", "page_count": "50"})
    rows = ((payload.get("list") or [])
            if classify(str(payload.get("status", ""))) is Action.OK else [])
    reports = [r for r in rows
               if any(k in str(r.get("report_nm", ""))
                      for k in ("사업보고서", "반기보고서", "분기보고서"))]
    best = max(reports, key=lambda r: str(r.get("rcept_dt", "")), default=None)
    slot.path.parent.mkdir(parents=True, exist_ok=True)
    slot.path.write_text(json.dumps(best or {}, ensure_ascii=False), encoding="utf-8")
    return best


def body_of(client: DartClient, rcept_no: str, *, ttl: int = DEFAULT_TTL) -> str:
    """공시 원문. 한 건이 7MB 를 넘으니 **캐시가 필수**다."""
    slot = Cached(CACHE / "body" / f"{rcept_no}.xml", ttl=ttl)
    if slot.fresh:
        return slot.path.read_text(encoding="utf-8", errors="ignore")
    raw = client.get_document(rcept_no)
    slot.path.parent.mkdir(parents=True, exist_ok=True)
    slot.path.write_text(raw, encoding="utf-8")
    return raw


def neighbours(edges: list[tuple[str, str, str]], corp_code: str,
               hops: int = 1) -> dict[str, int]:
    """지분으로 엮인 회사와 홉수. 방향을 안 가린다 — 노출은 방향을 안 가린다."""
    adj: dict[str, set[str]] = {}
    for a, b, *_ in edges:
        adj.setdefault(a, set()).add(b)
        adj.setdefault(b, set()).add(a)
    dist = {corp_code: 0}
    frontier = [corp_code]
    for step in range(1, hops + 1):
        nxt = []
        for node in frontier:
            for other in adj.get(node, ()):
                if other not in dist:
                    dist[other] = step
                    nxt.append(other)
        frontier = nxt
    dist.pop(corp_code, None)
    return dist
