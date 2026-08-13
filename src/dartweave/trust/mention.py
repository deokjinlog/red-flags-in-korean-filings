"""mention_count 집계.

요구사항 결정 3 — 집계 키는 (엣지 정체성, **출처 주체**) 다.
출처 주체 = (보고 회사, 보고서 종류). 같은 회사의 연차 반복은 1로 친다.
이 규칙을 어기면 자기 인용으로 가중치가 부풀려진다.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from dartweave.parse.relation import RelationEdge


# ⚠️ RISK(breaking): 아래 집계 키에 rcept_no 나 fiscal_year 를 절대 추가하지 말 것.
# 추가하는 순간 같은 회사의 연차 반복이 독립 근거로 세어져 자기 인용으로 가중치가 부풀려진다
# (AC-3 위반). 테스트 test_same_company_across_three_years_counts_as_one 이 이 경계를 지킨다.
# — by main(3-checklist: 식별 키 변경 = 신뢰도 산식 왜곡)
def count_mentions(
    pairs: Iterable[tuple[RelationEdge, str]],
) -> dict[str, int]:
    """pairs: (엣지, 보고서 종류) 목록 → {edge_key: 서로 다른 출처 주체 수}"""
    subjects: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for edge, report_kind in pairs:
        subject = (edge.reporter_corp_code or "", report_kind)
        subjects[edge.edge_key].add(subject)
    return {key: len(s) for key, s in subjects.items()}
