"""군집별 지표표 — 근거 블록의 본문.

`의존도 = 외부엣지 / 노드수`. 이 한 숫자가 "적은 수에 다수가 의존한다" 는 주장의
근거가 되므로, 정의를 코드 한 곳에 두고 표에 그대로 노출한다.

군집에 의미 라벨을 붙이지 않는다 (AC-4). "군집 3 = 소재" 라고 이름 붙이는 순간
결론이 데이터가 아니라 라벨에서 나온다.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass


# ⚠️ RISK(breaking): 여기에 의미 라벨 필드(`name`·`industry` 등)를 추가하면 AC-4 가
# 무너진다. "군집 3 = 소재" 라고 이름 붙이는 순간 결론이 데이터가 아니라 라벨에서
# 나온다. 필드 집합은 test_cluster_rows_have_no_semantic_label 이 고정하고 있다.
#
# ⚠️ RISK(side-effect): `external_edges` 는 **군집 하나의 관점**에서 센 값이라,
# 군집을 가로지르는 엣지 하나가 양쪽 행에 각각 1씩 잡힌다. 행별로는 맞지만 이
# 열을 전체 합산하면 실제 교차 엣지 수의 2배가 된다(실측 확인). 네트워크 전체
# 요약을 만들 때는 이 열을 더하지 말고 엣지를 직접 셀 것.
# — by main(3-checklist: 공개 스키마 / 집계 오독)
@dataclass(frozen=True)
class ClusterRow:
    cluster_id: int
    nodes: int
    internal_edges: int
    external_edges: int
    dependency_ratio: float
    mean_supply_depth: float | None


def cluster_metrics(
    edges: list[tuple[str, str, str]],
    membership: dict[str, int],
    *,
    depth: dict[str, float],
) -> list[ClusterRow]:
    members: dict[int, set[str]] = defaultdict(set)
    for node, cid in membership.items():
        members[cid].add(node)

    internal: dict[int, int] = defaultdict(int)
    external: dict[int, int] = defaultdict(int)
    for a, b, _ in edges:
        ca, cb = membership.get(a), membership.get(b)
        if ca is None or cb is None:
            continue
        if ca == cb:
            internal[ca] += 1
        else:
            external[ca] += 1
            external[cb] += 1

    rows: list[ClusterRow] = []
    for cid, nodes in sorted(members.items()):
        depths = [depth[n] for n in nodes if n in depth]
        rows.append(
            ClusterRow(
                cluster_id=cid,
                nodes=len(nodes),
                internal_edges=internal[cid],
                external_edges=external[cid],
                dependency_ratio=external[cid] / len(nodes) if nodes else 0.0,
                mean_supply_depth=(sum(depths) / len(depths)) if depths else None,
            )
        )
    return rows
