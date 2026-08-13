"""엣지 목록 내보내기 (AC-9).

세 목적을 겸한다:
  ① 차수 보존 귀무모형 (GDS 에 셔플 기능 없음)
  ② CPM 목적함수 재실행 (GDS Leiden 은 모듈러리티 전용)
  ③ GDS 장애 시 대체 경로
"""
from __future__ import annotations

import csv
from collections import defaultdict
from collections.abc import Iterable
from typing import Any, TextIO

EXPORT_HEADER = ["start", "end", "type", "weight", "fiscal_year"]


def write_edge_list(rows: Iterable[dict[str, Any]], out: TextIO) -> int:
    writer = csv.DictWriter(out, fieldnames=EXPORT_HEADER, lineterminator="\n")
    writer.writeheader()
    n = 0
    for row in rows:
        writer.writerow({k: row.get(k) for k in EXPORT_HEADER})
        n += 1
    return n


def degree_table(rows: Iterable[dict[str, Any]]) -> dict[str, dict[str, int]]:
    """노드별 입·출차수. 이 값이 셔플 전후로 보존되어야 귀무모형이 정직하다."""
    deg: dict[str, dict[str, int]] = defaultdict(lambda: {"out": 0, "in": 0})
    for row in rows:
        deg[row["start"]]["out"] += 1
        deg[row["end"]]["in"] += 1
    return dict(deg)
