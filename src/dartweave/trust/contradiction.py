"""모순 검출.

슬라이스 1은 **등급 A만** 다룬다 — 논리적으로 불가능한 것.
100% 를 넘을 수는 없으므로 논쟁의 여지가 없고, 둘 다 법정 신고 항목이라
변명이 불가능하다. B/C/D 는 본문 추출이 들어오는 슬라이스 2 소관.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from dartweave.parse.relation import EdgeType, RelationEdge
from dartweave.trust.scope import scope_key

# ⚠️ RISK(side-effect): 이 값이 1급 모순의 검출 건수를 직접 정한다. 0 으로 좁히면 반올림
# 누적만으로 정상 기업이 대량 위반으로 뜨고, 넓히면 진짜 초과분을 놓친다.
# 변경 시 반드시 검출 건수 전후 비교를 남길 것 (scope.py 의 RATIO_TOLERANCE 와 같은 성격).
# — by main(3-checklist: 하류 출력에 직결되는 임계값)
SUM_TOLERANCE = 0.5  # 반올림 누적 흡수. 이보다 좁히면 오탐이 쏟아진다.


@dataclass(frozen=True)
class Finding:
    grade: str
    edge_key: str
    detail: dict[str, Any]


def detect_grade_a(edges: list[RelationEdge]) -> list[Finding]:
    """지분 합계 > 100% — 같은 (대상, 스코프, 주식종류) 안에서만 합산한다."""
    buckets: dict[
        tuple[str, tuple[str, str], str], list[RelationEdge]
    ] = defaultdict(list)
    for e in edges:
        if e.edge_type is not EdgeType.MAJOR_SHAREHOLDER_OF:
            continue
        if e.share_pct is None:
            continue  # 미상은 0으로 치면 안 된다
        # 실데이터 반영: 주식 종류를 버킷 키에 포함한다. SK하이닉스는 같은 지분이
        # "보통주"/"의결권 있는 주식" 두 라벨로 중복 게시돼, 섞어 합산하면 20%가 40%가 된다.
        # 지분율 50% 이상 회사에서 이러면 100% 초과 = 가짜 1급 모순이 만들어진다.
        buckets[(e.target_corp_code or "", scope_key(e), e.stock_knd or "")].append(e)

    findings: list[Finding] = []
    for (target, scope, stock_knd), group in buckets.items():
        total = round(sum(e.share_pct or 0.0 for e in group), 6)
        if total <= 100.0 + SUM_TOLERANCE:
            continue
        findings.append(
            Finding(
                grade="A",
                edge_key=f"{target}|SHARE_SUM|{scope[0]}:{scope[1]}|{stock_knd}",
                detail={
                    "target_corp_code": target,
                    "fiscal_year": scope[0],
                    "as_of": scope[1],
                    "stock_knd": stock_knd,
                    "total": total,
                    "holders": [
                        {
                            "name": e.source_name,
                            "pct": e.share_pct,
                            "rcept_no": e.rcept_no,
                        }
                        for e in group
                    ],
                },
            )
        )
    return findings
