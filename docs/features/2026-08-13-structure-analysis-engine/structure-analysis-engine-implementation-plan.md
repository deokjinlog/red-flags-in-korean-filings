---
commit_policy: per-task
---

# 구조 분석 엔진 구현계획서

> **다음 단계 안내**: 이 계획을 task-by-task 로 실행하려면 `subagent-driven` (보조 에이전트 모드) 또는 `executing-plans` (인라인 모드) 를 사용하세요. 각 step 은 체크박스 (`- [ ]`) 형식이라 진행 상황 추적이 가능합니다.

**Goal:** 검증된 그래프에서 구조를 읽되, **결론이 파라미터·경계·표본에 휘둘리지 않는다는 증거를 함께 낸다.**

**Architecture:** 게이트 두 개(품질 G1 · 경계 G2)가 계산 **앞**을 막고, 통과하면 렌즈 → 가중치 → 투영 두 벌 → 군집/층위 → 지표표 → 검증 ③④ → 결론 판정 → 근거 블록 순으로 흐른다. `analyze()` 순수 함수가 중심이고 CLI 는 껍데기다.

**Tech Stack:** Python 3.13+ · igraph 1.0 (Leiden 모듈러리티 + **CPM**) · networkx 3.6 (차수보존 셔플) · pytest

**Spec inputs:**
- `structure-analysis-engine-requirements.md` — 결정 1~11 / AC-1~14
- `structure-analysis-engine-tech-design.md` — D1(igraph 단독) · D2(경계 게이트 비대칭) · D3(순수함수+얇은 CLI) · D4~D7

**설계 대비 의도적 편차 1건** — 기술설계 §2 는 `centrality.py` 를 별도 모듈로 뒀으나, 본 계획은 `topology.py` 에 합친다. 층위와 중심성은 **똑같이 방향 그래프에서 나오고 똑같이 경계 게이트(G2)에 걸린다** — 게이트를 두 모듈에 중복 구현하면 한쪽만 풀리는 사고가 난다. 모듈 수는 13 → 12 + CLI.

**실측 기준선**
- 경계 닫은 그래프 1,490 노드 (`data/boundary.log` AFTER): 모듈러리티 **0.8535** vs 귀무 **0.7230±0.0007** → z=193.8 · 효과크기 **+0.1305**
- 별도 탐침 (766 노드): CPM(0.005) **52군집** vs 모듈러리티 **38군집**
- 계획 작성 중 API 실측 (igraph 1.0.0 / networkx 3.6.1): 무구조 ER 그래프의 효과크기는 **±0.02** 범위 → 임계값 근거

---

## 1. 단계별 작업

### Task 1: 패키지 스캐폴딩 + 렌즈 (AC-1)

**Files:**
- Create: `src/dartweave/structure/__init__.py` · `src/dartweave/structure/lens.py`
- Test: `tests/structure/__init__.py` · `tests/structure/test_lens.py`

**Model**: haiku

- [ ] **Step 1: 실패하는 테스트 작성**

**수정 후** (new file: `tests/structure/test_lens.py`):
```python
import pytest

from dartweave.structure.lens import LENSES, Lens, apply_lens


def test_lens_holds_only_include_list():
    """AC-1 — 중간 가중치 상수가 존재하면 안 된다. 필드 자체를 두지 않는다."""
    for lens in LENSES.values():
        assert set(vars(lens)) == {"name", "include"}


def test_known_lenses_exist():
    assert set(LENSES) == {"supply", "governance", "people"}
    assert LENSES["governance"].include == frozenset(
        {"MAJOR_SHAREHOLDER_OF", "INVESTS_IN", "HOLDS_5PCT"}
    )


def test_apply_lens_keeps_only_included_types():
    edges = [("A", "B", "INVESTS_IN"), ("B", "C", "SUPPLIES_TO")]
    kept = apply_lens(edges, LENSES["governance"])
    assert kept == [("A", "B", "INVESTS_IN")]


def test_apply_lens_is_binary_not_weighted():
    """살리거나 죽이거나. 남은 엣지에 렌즈발 가중치가 붙지 않는다."""
    edges = [("A", "B", "INVESTS_IN")]
    assert apply_lens(edges, LENSES["governance"]) == edges


def test_unknown_lens_name_raises_with_available_list():
    from dartweave.structure.lens import resolve_lens

    with pytest.raises(ValueError) as ei:
        resolve_lens("nope")
    assert "supply" in str(ei.value)


def test_select_indices_lets_callers_filter_parallel_lists():
    """엣지와 근거(EdgeEvidence)는 같은 순서의 평행 리스트다.

    렌즈로 엣지만 거르면 근거와 어긋나 **가중치가 엉뚱한 엣지에 붙는다.**
    그래서 인덱스를 돌려주는 경로를 따로 둔다.
    """
    from dartweave.structure.lens import select_indices

    edges = [("A", "B", "SUPPLIES_TO"), ("B", "C", "INVESTS_IN"), ("C", "D", "HOLDS_5PCT")]
    assert select_indices(edges, LENSES["governance"]) == [1, 2]
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/structure/test_lens.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dartweave.structure'`

- [ ] **Step 3: 구현**

**수정 후** (new file: `src/dartweave/structure/__init__.py`):
```python
__all__ = ["lens"]
```

**수정 후** (new file: `tests/structure/__init__.py`):
```python
```

**수정 후** (new file: `src/dartweave/structure/lens.py`):
```python
"""렌즈 — "무엇을 보고 싶은가" 의 선언.

관계 타입을 **살리거나 죽이거나**만 한다. 중간값 튜닝을 하지 않는 이유는
`왜 0.1인데요?` 에 답할 방법이 없기 때문이다. 임의성을 이진 선택 하나로 격리한다.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Lens:
    name: str
    include: frozenset[str]


LENSES: dict[str, Lens] = {
    "supply": Lens("supply", frozenset({"SUPPLIES_TO", "PRODUCES"})),
    "governance": Lens(
        "governance",
        frozenset({"MAJOR_SHAREHOLDER_OF", "INVESTS_IN", "HOLDS_5PCT"}),
    ),
    "people": Lens("people", frozenset({"EXECUTIVE_OF"})),
}


def resolve_lens(name: str) -> Lens:
    if name not in LENSES:
        raise ValueError(f"알 수 없는 렌즈 '{name}'. 가능한 값: {', '.join(LENSES)}")
    return LENSES[name]


def select_indices(edges: list[tuple[str, str, str]], lens: Lens) -> list[int]:
    """살아남는 엣지의 인덱스. 평행 리스트(근거·가중치)를 같이 거르기 위한 것."""
    return [i for i, e in enumerate(edges) if e[2] in lens.include]


def apply_lens(
    edges: list[tuple[str, str, str]], lens: Lens
) -> list[tuple[str, str, str]]:
    return [edges[i] for i in select_indices(edges, lens)]
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/structure/test_lens.py -v`
Expected: PASS — 6 passed

- [ ] **Step 5: 커밋**

```bash
git add src/dartweave/structure tests/structure
git commit -m "feat(structure): 렌즈 프리셋 (include 목록만, 중간 가중치 상수 없음)"
```

---

### Task 2: 가중치 파생 (AC-2)

**Files:**
- Create: `src/dartweave/structure/weight.py`
- Test: `tests/structure/test_structure_weight.py`

**Model**: sonnet

- [ ] **Step 1: 실패하는 테스트 작성**

**수정 후** (new file: `tests/structure/test_structure_weight.py`):
```python
from dartweave.structure.weight import EdgeEvidence, edge_weights
from dartweave.trust.weight import Coefficients


def _ev(**kw):
    base = dict(
        is_structured=True,
        cross_confirmed=False,
        mention_count=1,
        share_pct=None,
        observed_precision=None,
    )
    base.update(kw)
    return EdgeEvidence(**base)


def test_weights_come_from_layer0_inputs():
    ws = edge_weights([_ev(), _ev(cross_confirmed=True)])
    assert ws[1] > ws[0]


def test_coefficient_override_changes_weights():
    """민감도 스윕이 계수를 흔들 수 있어야 한다 (AC-8)."""
    base = edge_weights([_ev(cross_confirmed=True)])
    swept = edge_weights(
        [_ev(cross_confirmed=True)], Coefficients(cross_confirm_bonus=1.0)
    )
    assert base[0] != swept[0]


def test_weights_are_positive():
    """igraph 가중치는 양수여야 한다 — 0 이하면 Leiden 이 엣지를 무시한다."""
    ws = edge_weights([_ev(share_pct=0.0), _ev(is_structured=False)])
    assert all(w > 0 for w in ws)


def test_text_edge_never_uses_raw_confidence():
    """층0 AC-4c 를 그대로 승계 — EdgeEvidence 에 confidence 필드 자체가 없다."""
    assert "confidence" not in EdgeEvidence.__dataclass_fields__
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/structure/test_structure_weight.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dartweave.structure.weight'`

- [ ] **Step 3: 구현**

**수정 후** (new file: `src/dartweave/structure/weight.py`):
```python
"""층0 인자 → igraph 엣지 가중치.

겹2(근거강도)·겹3(정량속성)은 층0 이 이미 정의했다. 여기서는 그걸 그대로 파생해
igraph 에 주입만 한다 — 층1이 별도 가중치 개념을 만들면 층0의 근거가 끊긴다.
"""
from __future__ import annotations

from dataclasses import dataclass

from dartweave.trust.weight import Coefficients, WeightInputs, evidence_weight

MIN_WEIGHT = 1e-6  # Leiden 이 엣지를 무시하지 않도록 하한을 둔다


@dataclass(frozen=True)
class EdgeEvidence:
    """가중치 산출에 필요한 층0 인자만. `confidence` 는 의도적으로 없다 (층0 AC-4c)."""

    is_structured: bool
    cross_confirmed: bool
    mention_count: int
    share_pct: float | None
    observed_precision: float | None


def edge_weights(
    evidence: list[EdgeEvidence], coef: Coefficients | None = None
) -> list[float]:
    out: list[float] = []
    for e in evidence:
        w = evidence_weight(
            WeightInputs(
                is_structured=e.is_structured,
                confidence=None,
                cross_confirmed=e.cross_confirmed,
                mention_count=e.mention_count,
                share_pct=e.share_pct,
                observed_precision=e.observed_precision,
            ),
            coef,
        )
        out.append(max(w, MIN_WEIGHT))
    return out
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/structure/test_structure_weight.py -v`
Expected: PASS — 4 passed

- [ ] **Step 5: 커밋**

```bash
git add src/dartweave/structure/weight.py tests/structure/test_structure_weight.py
git commit -m "feat(structure): 층0 인자에서 igraph 가중치 파생 (계수 스윕 가능)"
```

---

### Task 3: 투영 두 벌 + 경계 판정 (AC-3 · AC-14)

**Files:**
- Create: `src/dartweave/structure/project.py`
- Test: `tests/structure/test_project.py`

**Model**: sonnet

- [ ] **Step 1: 실패하는 테스트 작성**

**수정 후** (new file: `tests/structure/test_project.py`):
```python
from dartweave.structure.project import BoundaryReport, boundary_of, project

EDGES = [("A", "B", "INVESTS_IN"), ("B", "C", "INVESTS_IN")]


def test_natural_projection_keeps_direction():
    g = project(EDGES, undirected=False)
    assert g.is_directed()
    assert g.ecount() == 2


def test_undirected_projection_drops_direction():
    """Leiden 은 UNDIRECTED 를 요구한다 (요구사항 결정 3)."""
    g = project(EDGES, undirected=True)
    assert not g.is_directed()


def test_weights_are_attached_when_given():
    g = project(EDGES, undirected=False, weights=[2.0, 3.0])
    assert list(g.es["weight"]) == [2.0, 3.0]


def test_boundary_ratio_counts_nodes_without_own_filing():
    """자기 신고가 없는 노드 = 경계. 실측에서 이게 출입차수를 왜곡했다."""
    r = boundary_of(EDGES, interior={"A", "B"})
    assert isinstance(r, BoundaryReport)
    assert r.total == 3 and r.boundary == 1
    assert r.ratio == 1 / 3


def test_fully_closed_graph_has_zero_boundary():
    r = boundary_of(EDGES, interior={"A", "B", "C"})
    assert r.ratio == 0.0 and r.is_closed(max_ratio=0.0)


def test_is_closed_respects_threshold():
    r = boundary_of(EDGES, interior={"A", "B"})
    assert not r.is_closed(max_ratio=0.1)
    assert r.is_closed(max_ratio=0.5)
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/structure/test_project.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dartweave.structure.project'`

- [ ] **Step 3: 구현**

**수정 후** (new file: `src/dartweave/structure/project.py`):
```python
"""투영 두 벌 + 경계 판정.

Leiden 은 UNDIRECTED 를 요구하고 층위는 방향이 필요하다. 저장은 하나, 투영에서 갈린다.

경계 판정이 여기 있는 이유 (AC-14): 자기 신고가 없는 노드는 자기 쪽 엣지가 통째로
빠져 있어 출입차수가 인위적으로 왜곡된다. 실측 — 경계 열림에서 출차수 1위는 한화(85)
였는데, 닫고 나니 태영건설(119) 이었다. **경계 열린 상태의 방향 지표는 틀린 결론을 낸다.**
"""
from __future__ import annotations

from dataclasses import dataclass

import igraph as ig


@dataclass(frozen=True)
class BoundaryReport:
    total: int
    boundary: int

    @property
    def ratio(self) -> float:
        return self.boundary / self.total if self.total else 0.0

    def is_closed(self, *, max_ratio: float) -> bool:
        return self.ratio <= max_ratio


def boundary_of(
    edges: list[tuple[str, str, str]], interior: set[str]
) -> BoundaryReport:
    nodes = {v for e in edges for v in e[:2]}
    return BoundaryReport(total=len(nodes), boundary=len(nodes - interior))


def project(
    edges: list[tuple[str, str, str]],
    *,
    undirected: bool,
    weights: list[float] | None = None,
) -> ig.Graph:
    verts = sorted({v for e in edges for v in e[:2]})
    idx = {v: i for i, v in enumerate(verts)}
    g = ig.Graph(directed=True)
    g.add_vertices(len(verts))
    g.vs["corp_code"] = verts
    g.add_edges([(idx[a], idx[b]) for a, b, _ in edges])
    g.es["type"] = [t for _, _, t in edges]
    if weights is not None:
        g.es["weight"] = weights
    if undirected:
        # ⚠️ `combine_edges="sum"` 는 문자열 속성 `type` 에서 죽는다 (실측:
        # TypeError "product can only be invoked on numeric attributes").
        # 속성별로 지정해야 하고, `weight` 가 없어도 이 형태는 안전하다.
        g.to_undirected(combine_edges={"weight": "sum", "type": "first"})
    return g
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/structure/test_project.py -v`
Expected: PASS — 6 passed

- [ ] **Step 5: 커밋**

```bash
git add src/dartweave/structure/project.py tests/structure/test_project.py
git commit -m "feat(structure): 투영 두 벌 + 경계 비율 판정 (AC-3, AC-14)"
```

---

### Task 4: 군집 — Leiden 모듈러리티 + CPM 병행 (AC-6 · AC-2 가중 확인)

**Files:**
- Create: `src/dartweave/structure/cluster.py`
- Test: `tests/structure/test_cluster.py`

**Model**: sonnet

- [ ] **Step 1: 실패하는 테스트 작성**

**수정 후** (new file: `tests/structure/test_cluster.py`):
```python
import igraph as ig

from dartweave.structure.cluster import ClusterResult, cluster, compare_objectives


def _two_blobs() -> ig.Graph:
    """두 덩어리가 다리 하나로 연결된 그래프 — 군집이 분명히 존재한다."""
    edges = [(i, j) for i in range(5) for j in range(i + 1, 5)]
    edges += [(i, j) for i in range(5, 10) for j in range(i + 1, 10)]
    edges.append((4, 5))
    return ig.Graph(n=10, edges=edges, directed=False)


def test_cluster_returns_membership_and_modularity():
    r = cluster(_two_blobs(), objective="modularity")
    assert isinstance(r, ClusterResult)
    assert r.n_clusters == 2
    assert r.modularity > 0


def test_cpm_objective_is_supported():
    """GDS Leiden 은 모듈러리티 전용이라 CPM 은 igraph 로만 된다 (요구사항 결정 7)."""
    r = cluster(_two_blobs(), objective="CPM", resolution=0.1)
    assert r.n_clusters >= 2


def test_membership_covers_every_node():
    g = _two_blobs()
    r = cluster(g, objective="modularity")
    assert len(r.membership) == g.vcount()


def test_compare_objectives_reports_the_delta():
    """모듈러리티가 작은 군집을 놓치는지 보는 게 목적이다 (실측 38 vs 52)."""
    c = compare_objectives(_two_blobs(), cpm_resolution=0.1)
    assert set(c) == {"modularity_clusters", "cpm_clusters", "delta"}
    assert c["delta"] == c["cpm_clusters"] - c["modularity_clusters"]


def test_seed_makes_result_reproducible():
    g = _two_blobs()
    a = cluster(g, objective="modularity", seed=7)
    b = cluster(g, objective="modularity", seed=7)
    assert a.membership == b.membership


def test_weighted_run_differs_from_unweighted():
    """AC-2 — 가중치가 실제로 군집에 영향을 준다는 걸 확인 가능해야 한다.

    실측: 다리에 200 을 주면 무가중 2군집 → 가중 3군집으로 갈라진다.
    가중치를 붙였는데 결과가 같으면 주입이 안 된 것이다.
    """
    g = _two_blobs()
    unweighted = cluster(g, objective="modularity", seed=1)

    g.es["weight"] = [1.0] * (g.ecount() - 1) + [200.0]
    weighted = cluster(g, objective="modularity", seed=1)

    assert weighted.membership != unweighted.membership
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/structure/test_cluster.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dartweave.structure.cluster'`

- [ ] **Step 3: 구현**

**수정 후** (new file: `src/dartweave/structure/cluster.py`):
```python
"""군집 — Leiden. Louvain 은 쓰지 않는다.

Louvain 은 연결조차 안 된 군집을 만들 수 있다(최대 25% 불량 연결, 16% 분리).
Leiden 은 연결성을 증명으로 보장한다 (Traag et al., Sci Rep 9:5233, 2019).

CPM 병행이 필수인 이유: 모듈러리티 최적화는 네트워크 크기에 의존하는 규모보다 작은
모듈을 원리적으로 못 본다 (Fortunato & Barthélemy, PNAS 104(1), 2007).
실측 — CPM(0.005) 52군집 vs 모듈러리티 38군집. **14개를 놓친다.**
"""
from __future__ import annotations

import random
from dataclasses import dataclass

import igraph as ig

N_ITERATIONS = 10


@dataclass(frozen=True)
class ClusterResult:
    membership: list[int]
    modularity: float
    n_clusters: int
    objective: str
    resolution: float


def cluster(
    g: ig.Graph,
    *,
    objective: str = "modularity",
    resolution: float = 1.0,
    seed: int | None = None,
) -> ClusterResult:
    if seed is not None:
        # ⚠️ 전역 상태다. 병렬화하면 시드가 경합한다 (§2 참조).
        ig.set_random_number_generator(random.Random(seed))
    weights = g.es["weight"] if "weight" in g.es.attributes() else None
    vc = g.community_leiden(
        objective_function=objective,
        resolution=resolution,
        weights=weights,
        n_iterations=N_ITERATIONS,
    )
    return ClusterResult(
        membership=list(vc.membership),
        modularity=g.modularity(vc.membership, weights=weights),
        n_clusters=len(vc),
        objective=objective,
        resolution=resolution,
    )


def compare_objectives(
    g: ig.Graph, *, resolution: float = 1.0, cpm_resolution: float = 0.005
) -> dict[str, int]:
    """모듈러리티가 놓친 군집 수를 드러낸다. 차이 자체가 보고 대상이다."""
    m = cluster(g, objective="modularity", resolution=resolution)
    c = cluster(g, objective="CPM", resolution=cpm_resolution)
    return {
        "modularity_clusters": m.n_clusters,
        "cpm_clusters": c.n_clusters,
        "delta": c.n_clusters - m.n_clusters,
    }
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/structure/test_cluster.py -v`
Expected: PASS — 6 passed

- [ ] **Step 5: 커밋**

```bash
git add src/dartweave/structure/cluster.py tests/structure/test_cluster.py
git commit -m "feat(structure): Leiden 군집 + CPM 병행 비교 (모듈러리티가 놓친 수 노출)"
```

---

### Task 5: 차수 보존 귀무모형 (AC-5)

**Files:**
- Create: `src/dartweave/structure/nullmodel.py`
- Test: `tests/structure/test_nullmodel.py`

**Model**: sonnet

- [ ] **Step 1: 실패하는 테스트 작성**

**수정 후** (new file: `tests/structure/test_nullmodel.py`):
```python
import igraph as ig

from dartweave.structure.nullmodel import NullResult, degree_preserving_null


def _two_blobs() -> ig.Graph:
    edges = [(i, j) for i in range(6) for j in range(i + 1, 6)]
    edges += [(i, j) for i in range(6, 12) for j in range(i + 1, 12)]
    edges.append((5, 6))
    return ig.Graph(n=12, edges=edges, directed=False)


def test_shuffle_preserves_degree_sequence():
    """완전 무작위 셔플은 허브까지 없애 귀무모형을 부당하게 낮춘다."""
    g = _two_blobs()
    r = degree_preserving_null(g, runs=3, seed=1)
    assert r.degree_preserved is True


def test_structured_graph_scores_above_its_null():
    g = _two_blobs()
    r = degree_preserving_null(g, runs=10, seed=1)
    assert isinstance(r, NullResult)
    assert r.actual > r.mean
    assert r.z > 0


def test_runs_count_is_reported():
    """AC-5 — 반복 횟수가 출력에 명시돼야 한다."""
    r = degree_preserving_null(_two_blobs(), runs=7, seed=1)
    assert r.runs == 7


def test_random_graph_has_small_effect_size():
    """무구조 그래프는 귀무모형과 구분되지 않아야 한다.

    z 가 아니라 효과크기로 본다 — sd 가 작으면 z 는 무구조에서도 크게 뜬다.
    """
    ig.set_random_number_generator(__import__("random").Random(1))
    g = ig.Graph.Erdos_Renyi(n=40, m=120)
    r = degree_preserving_null(g, runs=8, seed=1)
    assert abs(r.effect_size) < 0.05


def test_graph_too_small_to_shuffle_is_reported_not_swallowed():
    """4노드 미만은 셔플 자체가 불가능하다 (nx.NetworkXError).

    실측: 삼각형은 3회 시도 3회 실패 → 귀무 = 실제 → 효과크기 0.
    조용히 통과시키면 '구조 없음' 과 '판정 불가' 가 구분되지 않는다.
    """
    tri = ig.Graph(n=3, edges=[(0, 1), (1, 2), (2, 0)], directed=False)
    r = degree_preserving_null(tri, runs=3, seed=1)
    assert r.swaps_failed == 3
    assert r.effect_size == 0.0
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/structure/test_nullmodel.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dartweave.structure.nullmodel'`

- [ ] **Step 3: 구현**

**수정 후** (new file: `src/dartweave/structure/nullmodel.py`):
```python
"""차수 보존 귀무모형.

모듈러리티에 절대 기준을 쓰지 않는 이유는 희소 그래프가 무작위여도 높게 나오기
때문이다. 실측 — 실제 0.8535 인데 **귀무모형이 이미 0.7230**. 절대 기준(0.3)을 썼으면
"매우 우수" 라고 판단했을 것이고, 실제 신호는 효과크기 +0.1305 뿐이다.

셔플은 반드시 차수를 보존해야 한다. 완전 무작위는 허브 구조까지 파괴해서 귀무
모듈러리티를 부당하게 낮추고, 그러면 "구조가 없어서" 가 아니라 "허브를 없애서" 나온
숫자로 승리를 선언하게 된다.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass

import igraph as ig
import networkx as nx


@dataclass(frozen=True)
class NullResult:
    actual: float
    mean: float
    sd: float
    runs: int
    degree_preserved: bool
    swaps_failed: int

    @property
    def z(self) -> float:
        return (self.actual - self.mean) / self.sd if self.sd else float("inf")

    @property
    def effect_size(self) -> float:
        """실제 - 귀무. z 는 표준편차가 작으면 부풀려지므로 이걸 함께 본다."""
        return self.actual - self.mean


def _to_nx(g: ig.Graph) -> nx.Graph:
    h = nx.Graph()
    h.add_nodes_from(range(g.vcount()))
    h.add_edges_from([(e.source, e.target) for e in g.es])
    return h


def degree_preserving_null(
    g: ig.Graph, *, runs: int = 20, seed: int = 1
) -> NullResult:
    actual = g.community_leiden(
        objective_function="modularity", n_iterations=10
    ).modularity
    base = _to_nx(g)
    before = sorted(d for _, d in base.degree())

    scores: list[float] = []
    preserved = True
    failed = 0
    for _ in range(runs):
        h = base.copy()
        try:
            nx.double_edge_swap(
                h,
                nswap=h.number_of_edges() * 2,
                max_tries=h.number_of_edges() * 50,
                seed=seed,
            )
        # ⚠️ 둘은 형제 예외다. `NetworkXAlgorithmError` 는 `NetworkXError` 의
        # 하위가 **아니라서** 하나만 잡으면 4노드 미만 그래프에서 통째로 터진다
        # (실측: "Graph has fewer than four nodes" 는 NetworkXError).
        except (nx.NetworkXError, nx.NetworkXAlgorithmError):
            failed += 1
        if sorted(d for _, d in h.degree()) != before:
            preserved = False
        gi = ig.Graph(n=h.number_of_nodes(), edges=list(h.edges()), directed=False)
        scores.append(
            gi.community_leiden(
                objective_function="modularity", n_iterations=10
            ).modularity
        )

    return NullResult(
        actual=actual,
        mean=statistics.mean(scores),
        sd=statistics.stdev(scores) if len(scores) > 1 else 0.0,
        runs=runs,
        degree_preserved=preserved,
        swaps_failed=failed,
    )
```

> 셔플이 전부 실패하면(너무 작은 그래프) 귀무 = 실제 → 효과크기 0 → `결론 없음`.
> 조용히 넘어가지 않도록 `swaps_failed` 로 드러낸다.

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/structure/test_nullmodel.py -v`
Expected: PASS — 5 passed

- [ ] **Step 5: 커밋**

```bash
git add src/dartweave/structure/nullmodel.py tests/structure/test_nullmodel.py
git commit -m "feat(structure): 차수보존 귀무모형 (절대기준 금지, 효과크기 병기)"
```

---

### Task 6: 층위 + 중심성 (AC-4 · AC-14)

**Files:**
- Create: `src/dartweave/structure/topology.py`
- Test: `tests/structure/test_topology.py`

**Model**: sonnet

- [ ] **Step 1: 실패하는 테스트 작성**

**수정 후** (new file: `tests/structure/test_topology.py`):
```python
import pytest

from dartweave.structure.project import boundary_of, project
from dartweave.structure.topology import BoundaryNotClosed, topology

EDGES = [("A", "B", "INVESTS_IN"), ("B", "C", "INVESTS_IN")]
CLOSED = {"A", "B", "C"}


def test_topology_reports_in_and_out_degree_separately():
    g = project(EDGES, undirected=False)
    t = topology(g, boundary_of(EDGES, CLOSED), max_boundary_ratio=0.0)
    assert t.out_degree["A"] == 1 and t.in_degree["A"] == 0
    assert t.in_degree["C"] == 1 and t.out_degree["C"] == 0


def test_supply_depth_places_source_upstream():
    g = project(EDGES, undirected=False)
    t = topology(g, boundary_of(EDGES, CLOSED), max_boundary_ratio=0.0)
    assert t.depth["A"] < t.depth["C"]


def test_open_boundary_refuses_to_compute():
    """AC-14 — 경계가 열린 상태의 방향 지표는 틀린 결론을 낸다."""
    g = project(EDGES, undirected=False)
    with pytest.raises(BoundaryNotClosed) as ei:
        topology(g, boundary_of(EDGES, {"A"}), max_boundary_ratio=0.1)
    assert "경계" in str(ei.value)


def test_betweenness_is_included_when_closed():
    g = project(EDGES, undirected=False)
    t = topology(g, boundary_of(EDGES, CLOSED), max_boundary_ratio=0.0)
    assert t.betweenness["B"] > t.betweenness["A"]


def test_no_cluster_label_is_produced():
    """AC-4 — 군집에 의미 라벨을 붙이는 경로가 없어야 한다."""
    g = project(EDGES, undirected=False)
    t = topology(g, boundary_of(EDGES, CLOSED), max_boundary_ratio=0.0)
    assert not hasattr(t, "labels")
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/structure/test_topology.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dartweave.structure.topology'`

- [ ] **Step 3: 구현**

**수정 후** (new file: `src/dartweave/structure/topology.py`):
```python
"""층위 + 중심성 — 방향이 필요한 지표. 경계가 닫힌 뒤에만 계산한다.

군집(누구와 뭉치나)과 층위(공급망 어디쯤)는 다른 질문이다. 커뮤니티 탐지는 엣지 밀도만
보므로 계열사끼리 뭉치지 밸류체인 단계를 답하지 않는다. 층위는 방향 그래프의 위상에서
나온다 — 그래서 별도 모듈이고, 별도라는 사실 자체가 AC-4 의 분리 증거다.

경계 게이트가 여기에만 걸리는 이유: 실측상 군집은 경계에 견디지만(효과크기
+0.1211→+0.1305) 방향 지표는 뒤집힌다(출차수 1위 한화→태영건설).
"""
from __future__ import annotations

from dataclasses import dataclass

import igraph as ig

from dartweave.structure.project import BoundaryReport


class BoundaryNotClosed(RuntimeError):
    """경계가 열린 상태에서 층위·중심성을 요구했을 때."""


@dataclass(frozen=True)
class Topology:
    in_degree: dict[str, int]
    out_degree: dict[str, int]
    depth: dict[str, float]
    betweenness: dict[str, float]
    boundary_ratio: float


def topology(
    g: ig.Graph, boundary: BoundaryReport, *, max_boundary_ratio: float
) -> Topology:
    if not boundary.is_closed(max_ratio=max_boundary_ratio):
        raise BoundaryNotClosed(
            f"경계 비율 {boundary.ratio:.1%} > 허용 {max_boundary_ratio:.1%} — "
            "층위·중심성은 산출하지 않는다. 경계 노드의 신고를 먼저 수집할 것."
        )

    codes = list(g.vs["corp_code"])
    outd = g.degree(mode="out")
    ind = g.degree(mode="in")
    und = g.copy()
    und.to_undirected(combine_edges="ignore")
    und.simplify()
    btw = und.betweenness()

    # 공급 깊이: 입차수 비중이 높을수록 하류. 0(순수 상류) ~ 1(순수 하류).
    depth = {}
    for i, c in enumerate(codes):
        total = ind[i] + outd[i]
        depth[c] = (ind[i] / total) if total else 0.0

    return Topology(
        in_degree=dict(zip(codes, ind)),
        out_degree=dict(zip(codes, outd)),
        depth=depth,
        betweenness=dict(zip(codes, btw)),
        boundary_ratio=boundary.ratio,
    )
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/structure/test_topology.py -v`
Expected: PASS — 5 passed

- [ ] **Step 5: 커밋**

```bash
git add src/dartweave/structure/topology.py tests/structure/test_topology.py
git commit -m "feat(structure): 층위·중심성 + 경계 게이트 (열려 있으면 산출 거부)"
```

---

### Task 7: 군집별 지표표

**Files:**
- Create: `src/dartweave/structure/metrics.py`
- Test: `tests/structure/test_metrics.py`

**Model**: sonnet

- [ ] **Step 1: 실패하는 테스트 작성**

**수정 후** (new file: `tests/structure/test_metrics.py`):
```python
from dartweave.structure.metrics import cluster_metrics

# 군집 0 = {A,B}, 군집 1 = {C,D}. 다리 하나(B-C).
EDGES = [
    ("A", "B", "INVESTS_IN"),
    ("C", "D", "INVESTS_IN"),
    ("B", "C", "INVESTS_IN"),
]
MEMBERSHIP = {"A": 0, "B": 0, "C": 1, "D": 1}


def test_internal_and_external_edges_are_separated():
    rows = {r.cluster_id: r for r in cluster_metrics(EDGES, MEMBERSHIP, depth={})}
    assert rows[0].internal_edges == 1
    assert rows[0].external_edges == 1


def test_dependency_ratio_is_external_over_nodes():
    rows = {r.cluster_id: r for r in cluster_metrics(EDGES, MEMBERSHIP, depth={})}
    assert rows[0].dependency_ratio == 0.5  # 외부 1 / 노드 2


def test_mean_depth_uses_supplied_depths():
    depth = {"A": 0.0, "B": 0.5, "C": 0.5, "D": 1.0}
    rows = {r.cluster_id: r for r in cluster_metrics(EDGES, MEMBERSHIP, depth=depth)}
    assert rows[0].mean_supply_depth == 0.25


def test_missing_depth_yields_none_not_zero():
    """깊이를 못 구한 걸 0(순수 상류)으로 치면 없는 결론이 생긴다."""
    rows = {r.cluster_id: r for r in cluster_metrics(EDGES, MEMBERSHIP, depth={})}
    assert rows[0].mean_supply_depth is None


def test_cluster_rows_have_no_semantic_label():
    """AC-4 — 군집 번호와 수치만. '소재 군집' 같은 이름을 만들지 않는다."""
    row = cluster_metrics(EDGES, MEMBERSHIP, depth={})[0]
    assert set(vars(row)) == {
        "cluster_id",
        "nodes",
        "internal_edges",
        "external_edges",
        "dependency_ratio",
        "mean_supply_depth",
    }
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/structure/test_metrics.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dartweave.structure.metrics'`

- [ ] **Step 3: 구현**

**수정 후** (new file: `src/dartweave/structure/metrics.py`):
```python
"""군집별 지표표 — 근거 블록의 본문.

`의존도 = 외부엣지 / 노드수`. 이 한 숫자가 "적은 수에 다수가 의존한다" 는 주장의
근거가 되므로, 정의를 코드 한 곳에 두고 표에 그대로 노출한다.

군집에 의미 라벨을 붙이지 않는다 (AC-4). "군집 3 = 소재" 라고 이름 붙이는 순간
결론이 데이터가 아니라 라벨에서 나온다.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass


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
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/structure/test_metrics.py -v`
Expected: PASS — 5 passed

- [ ] **Step 5: 커밋**

```bash
git add src/dartweave/structure/metrics.py tests/structure/test_metrics.py
git commit -m "feat(structure): 군집별 지표표 (의존도 정의 단일화, 라벨 없음)"
```

---

### Task 8: 민감도 스윕 — 해상도(AC-7) + 겹2 계수(AC-8)

**Files:**
- Create: `src/dartweave/structure/sensitivity.py`
- Test: `tests/structure/test_sensitivity.py`

**Model**: sonnet

- [ ] **Step 1: 실패하는 테스트 작성**

**수정 후** (new file: `tests/structure/test_sensitivity.py`):
```python
import igraph as ig

from dartweave.structure.sensitivity import RESOLUTIONS, SweepResult, resolution_sweep


def _two_blobs() -> ig.Graph:
    edges = [(i, j) for i in range(6) for j in range(i + 1, 6)]
    edges += [(i, j) for i in range(6, 12) for j in range(i + 1, 12)]
    edges.append((5, 6))
    return ig.Graph(n=12, edges=edges, directed=False)


def test_default_sweep_has_at_least_four_points():
    """AC-7 — 최소 4개 값."""
    assert len(RESOLUTIONS) >= 4


def test_sweep_reports_every_point():
    r = resolution_sweep(_two_blobs())
    assert isinstance(r, SweepResult)
    assert len(r.points) == len(RESOLUTIONS)
    assert {p.resolution for p in r.points} == set(RESOLUTIONS)


def test_stable_structure_holds_across_the_sweep():
    r = resolution_sweep(_two_blobs())
    assert r.holds is True


def test_wildly_varying_cluster_count_does_not_hold():
    """실측: 해상도 0.5→2.0 에서 최대군집 126→69. 이런 결론은 반려돼야 한다.

    합성 확인: 무구조 그래프의 최대군집 비중이 0.787→0.087 (spread 0.7) 로 무너진다.
    """
    ig.set_random_number_generator(__import__("random").Random(1))
    r = resolution_sweep(ig.Graph.Erdos_Renyi(n=80, m=240), tolerance=0.05)
    assert r.holds is False
    assert r.spread > 0.5


def test_points_carry_cluster_count_and_largest():
    r = resolution_sweep(_two_blobs())
    p = r.points[0]
    assert p.n_clusters > 0 and p.largest_cluster > 0


# --- AC-8: 겹2 계수 스윕 -----------------------------------------------------


def _edges_and_evidence():
    from dartweave.structure.weight import EdgeEvidence

    edges, ev = [], []
    for b in range(2):
        members = [f"B{b}N{i}" for i in range(5)]
        for i in range(5):
            for j in range(i + 1, 5):
                edges.append((members[i], members[j], "INVESTS_IN"))
                ev.append(EdgeEvidence(True, False, 1, None, None))
    edges.append(("B0N4", "B1N0", "INVESTS_IN"))
    ev.append(EdgeEvidence(True, True, 5, None, None))  # 다리만 교차확인+반복언급
    return edges, ev


def test_coefficient_sweep_covers_default_cases():
    """AC-8 — 해상도뿐 아니라 겹2 계수도 흔들어야 한다."""
    from dartweave.structure.sensitivity import COEFFICIENT_CASES, coefficient_sweep

    edges, ev = _edges_and_evidence()
    r = coefficient_sweep(edges, ev)
    assert len(r.points) == len(COEFFICIENT_CASES) >= 3


def test_coefficient_sweep_reports_holds():
    from dartweave.structure.sensitivity import coefficient_sweep

    edges, ev = _edges_and_evidence()
    assert isinstance(coefficient_sweep(edges, ev).holds, bool)


def test_coefficient_case_labels_are_human_readable():
    """반려 사유를 사람이 읽어야 한다 — 어떤 계수에서 뒤집혔는지."""
    from dartweave.structure.sensitivity import coefficient_sweep

    edges, ev = _edges_and_evidence()
    labels = [p.label for p in coefficient_sweep(edges, ev).points]
    assert "baseline" in labels
    assert all(isinstance(x, str) and x for x in labels)
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/structure/test_sensitivity.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dartweave.structure.sensitivity'`

- [ ] **Step 3: 구현**

**수정 후** (new file: `src/dartweave/structure/sensitivity.py`):
```python
"""민감도 스윕 — 부록이 아니라 결론 판정의 입력이다.

실측: 해상도 0.5→2.0 에서 최대 군집이 126→69 로 반토막 났다. *"가장 큰 군집이 N개사"*
류 결론은 이 구간을 못 버틴다. 특정 구간에서만 성립하는 결론은 파라미터를 잘 골라서
나온 우연이므로 보고하지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass

import igraph as ig

from dartweave.structure.cluster import cluster
from dartweave.structure.project import project
from dartweave.structure.weight import EdgeEvidence, edge_weights
from dartweave.trust.weight import Coefficients

RESOLUTIONS: tuple[float, ...] = (0.5, 0.8, 1.0, 1.2, 1.5, 2.0)
DEFAULT_TOLERANCE = 0.5  # 최대군집 비중의 허용 변동폭

# AC-8 — 겹2 계수는 임의값이다. 결론이 그 임의값에 기대고 있으면 결론이 아니다.
COEFFICIENT_CASES: tuple[tuple[str, Coefficients], ...] = (
    ("baseline", Coefficients()),
    ("cross_confirm_off", Coefficients(cross_confirm_bonus=1.0)),
    ("cross_confirm_strong", Coefficients(cross_confirm_bonus=3.0)),
    ("mention_flat", Coefficients(mention_step=0.0)),
    ("mention_steep", Coefficients(mention_step=0.3, mention_cap=3.0)),
)


@dataclass(frozen=True)
class SweepPoint:
    resolution: float
    n_clusters: int
    largest_cluster: int
    largest_share: float
    label: str = ""


@dataclass(frozen=True)
class SweepResult:
    points: list[SweepPoint]
    holds: bool
    spread: float


def resolution_sweep(
    g: ig.Graph,
    *,
    resolutions: tuple[float, ...] = RESOLUTIONS,
    tolerance: float = DEFAULT_TOLERANCE,
) -> SweepResult:
    points: list[SweepPoint] = []
    for res in resolutions:
        points.append(_point(g, resolution=res, label=f"resolution={res}"))
    return _summarize(points, tolerance)


def coefficient_sweep(
    edges: list[tuple[str, str, str]],
    evidence: list[EdgeEvidence],
    *,
    resolution: float = 1.0,
    tolerance: float = DEFAULT_TOLERANCE,
    cases: tuple[tuple[str, Coefficients], ...] = COEFFICIENT_CASES,
) -> SweepResult:
    """겹2 계수를 흔들어도 결론이 버티는가 (AC-8).

    해상도 스윕과 형태는 같지만 흔드는 대상이 다르다 — 이쪽은 **가중치를 다시
    계산해서** 그래프를 새로 만든다. 계수가 바뀌면 엣지 굵기가 바뀌고, 굵기가
    바뀌면 군집 경계가 움직인다.
    """
    points: list[SweepPoint] = []
    for label, coef in cases:
        g = project(edges, undirected=True, weights=edge_weights(evidence, coef))
        points.append(_point(g, resolution=resolution, label=label))
    return _summarize(points, tolerance)


def _point(ig_graph: ig.Graph, *, resolution: float, label: str) -> SweepPoint:
    r = cluster(ig_graph, objective="modularity", resolution=resolution, seed=1)
    sizes: dict[int, int] = {}
    for m in r.membership:
        sizes[m] = sizes.get(m, 0) + 1
    largest = max(sizes.values()) if sizes else 0
    return SweepPoint(
        resolution=resolution,
        n_clusters=r.n_clusters,
        largest_cluster=largest,
        largest_share=largest / ig_graph.vcount() if ig_graph.vcount() else 0.0,
        label=label,
    )


def _summarize(points: list[SweepPoint], tolerance: float) -> SweepResult:
    shares = [p.largest_share for p in points]
    spread = max(shares) - min(shares) if shares else 0.0
    return SweepResult(points=points, holds=spread <= tolerance, spread=spread)
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/structure/test_sensitivity.py -v`
Expected: PASS — 8 passed

- [ ] **Step 5: 커밋**

```bash
git add src/dartweave/structure/sensitivity.py tests/structure/test_sensitivity.py
git commit -m "feat(structure): 해상도 + 겹2 계수 민감도 스윕 (결론 판정의 입력)"
```

---

### Task 9: 결론 판정 3상태 (AC-10)

**Files:**
- Create: `src/dartweave/structure/verdict.py`
- Test: `tests/structure/test_verdict.py`

**Model**: sonnet

- [ ] **Step 1: 실패하는 테스트 작성**

**수정 후** (new file: `tests/structure/test_verdict.py`):
```python
from dartweave.structure.verdict import Verdict, decide


def test_stable_and_significant_is_accepted():
    v = decide(z=190.0, effect_size=0.13, sweep_holds=True, has_outlier=True)
    assert v is Verdict.ACCEPTED


def test_flat_metrics_yield_no_conclusion():
    """지표가 평평하면 '집중이 관측되지 않는다' 가 결론이다 — 이것도 발견이다."""
    v = decide(z=190.0, effect_size=0.13, sweep_holds=True, has_outlier=False)
    assert v is Verdict.NO_CONCLUSION


def test_unstable_sweep_is_parameter_dependent():
    v = decide(z=190.0, effect_size=0.13, sweep_holds=False, has_outlier=True)
    assert v is Verdict.PARAMETER_DEPENDENT


def test_weak_structure_yields_no_conclusion():
    v = decide(z=1.2, effect_size=0.004, sweep_holds=True, has_outlier=True)
    assert v is Verdict.NO_CONCLUSION


def test_er_noise_level_effect_does_not_pass():
    """무구조 ER 그래프 실측 상한(+0.02)이 임계를 넘으면 안 된다.

    z 는 크게 뜰 수 있다(귀무 sd 가 0.0005 수준) — 그래서 효과크기가 잡는다.
    """
    v = decide(z=40.0, effect_size=0.02, sweep_holds=True, has_outlier=True)
    assert v is Verdict.NO_CONCLUSION


def test_measured_real_signal_passes():
    """실측 기준선(+0.1305 · z=193.8)은 통과해야 한다 — 임계가 과하면 안 된다."""
    v = decide(z=193.8, effect_size=0.1305, sweep_holds=True, has_outlier=True)
    assert v is Verdict.ACCEPTED


def test_all_states_are_the_same_type():
    """AC-10 — 세 상태가 동등한 반환값. '결론 없음' 이 예외가 아니다."""
    results = [
        decide(z=190.0, effect_size=0.13, sweep_holds=True, has_outlier=True),
        decide(z=190.0, effect_size=0.13, sweep_holds=True, has_outlier=False),
        decide(z=190.0, effect_size=0.13, sweep_holds=False, has_outlier=True),
    ]
    assert all(isinstance(r, Verdict) for r in results)
    assert len(set(results)) == 3
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/structure/test_verdict.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dartweave.structure.verdict'`

- [ ] **Step 3: 구현**

**수정 후** (new file: `src/dartweave/structure/verdict.py`):
```python
"""결론 판정 — 세 상태가 동등하다.

이 층의 가장 큰 위험은 기술적 실패가 아니라 **데이터를 결론에 맞추는 것**이다.
하이라이트가 나와야 한다는 압력이 있으면 파라미터를 만질 유혹이 생긴다.
그래서 `결론 없음` 을 예외가 아닌 정식 반환값으로 두고, 스윕에 반려 권한을 준다.
"""
from __future__ import annotations

from enum import Enum

MIN_Z = 3.0
# 실측 접지: 무구조 ER 그래프의 효과크기가 ±0.02 까지 흔들린다 (igraph 1.0.0 측정).
# 임계를 0.02 에 두면 잡음이 통과한다. 실제 신호는 +0.1305 였으므로 0.05 는
# 잡음의 2.5배이면서 실측 신호의 1/2.6 — 양쪽에서 안전하다.
MIN_EFFECT = 0.05


class Verdict(Enum):
    ACCEPTED = "accepted"
    NO_CONCLUSION = "no_conclusion"
    PARAMETER_DEPENDENT = "parameter_dependent"


def decide(
    *, z: float, effect_size: float, sweep_holds: bool, has_outlier: bool
) -> Verdict:
    """판정 순서가 중요하다 — 불안정을 먼저 걸러야 우연을 채택하지 않는다."""
    if not sweep_holds:
        return Verdict.PARAMETER_DEPENDENT
    if z < MIN_Z or effect_size < MIN_EFFECT:
        return Verdict.NO_CONCLUSION
    if not has_outlier:
        return Verdict.NO_CONCLUSION
    return Verdict.ACCEPTED
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/structure/test_verdict.py -v`
Expected: PASS — 7 passed

- [ ] **Step 5: 커밋**

```bash
git add src/dartweave/structure/verdict.py tests/structure/test_verdict.py
git commit -m "feat(structure): 결론 판정 3상태 동등 반환 (결론 없음은 실패가 아니다)"
```

---

### Task 10: 근거 블록 직렬화 (AC-11 · AC-12 임계값 노출 · AC-13)

**Files:**
- Create: `src/dartweave/structure/evidence.py`
- Test: `tests/structure/test_evidence.py`

**Model**: sonnet

- [ ] **Step 1: 실패하는 테스트 작성**

**수정 후** (new file: `tests/structure/test_evidence.py`):
```python
import json

from dartweave.structure.evidence import EvidenceBlock, Scope, Thresholds, to_json
from dartweave.structure.metrics import ClusterRow
from dartweave.structure.verdict import Verdict


def _block() -> EvidenceBlock:
    return EvidenceBlock(
        lens="governance",
        include_types=["MAJOR_SHAREHOLDER_OF"],
        objective="modularity",
        resolution=1.0,
        clusters=[ClusterRow(0, 11, 34, 287, 26.1, 0.4)],
        modularity=0.8535,
        null_mean=0.7230,
        null_sd=0.0007,
        null_runs=20,
        cpm_clusters=52,
        cpm_delta=14,
        sweep_holds=True,
        sweep_spread=0.08,
        coef_sweep_holds=True,
        coef_sweep_spread=0.03,
        corporate_resolution_rate=0.60,
        scope=Scope(industry="건설", companies=1490, disclosures=2984,
                    fiscal_year="2024", boundary_ratio=0.0),
        thresholds=Thresholds(0.8, 0.0, 0.05, 3.0, 0.5),
        verdict=Verdict.ACCEPTED,
    )


def test_scope_is_mandatory_and_carries_boundary_ratio():
    """AC-13 + AC-14 가 한 필드에서 만난다."""
    d = json.loads(to_json(_block()))
    assert d["scope"]["boundary_ratio"] == 0.0
    assert d["scope"]["companies"] == 1490
    assert d["scope"]["industry"] == "건설"


def test_thresholds_are_published_not_buried():
    """AC-12 — 통과/반려 사유를 산출물만 보고 재구성할 수 있어야 한다."""
    d = json.loads(to_json(_block()))
    assert d["thresholds"]["min_effect_size"] == 0.05
    assert d["thresholds"]["min_corporate_resolution_rate"] == 0.8


def test_both_sweeps_are_reported():
    """AC-7(해상도) 과 AC-8(겹2 계수) 은 별개 축이라 따로 나와야 한다."""
    s = json.loads(to_json(_block()))["verification"]["stability"]
    assert set(s) == {"resolution", "coefficients"}
    assert s["coefficients"]["spread"] == 0.03


def test_verification_carries_null_model_not_just_modularity():
    """모듈러리티만 내면 절대 기준으로 오독된다."""
    d = json.loads(to_json(_block()))
    v = d["verification"]["structure"]
    assert v["null_mean"] == 0.7230 and v["runs"] == 20
    assert v["effect_size"] == round(0.8535 - 0.7230, 6)


def test_cpm_delta_is_exposed():
    d = json.loads(to_json(_block()))
    assert d["verification"]["structure"]["cpm_delta"] == 14


def test_verdict_serializes_as_string():
    d = json.loads(to_json(_block()))
    assert d["verdict"] == "accepted"


def test_json_roundtrips():
    assert json.loads(to_json(_block())) == json.loads(to_json(_block()))
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/structure/test_evidence.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dartweave.structure.evidence'`

- [ ] **Step 3: 구현**

**수정 후** (new file: `src/dartweave/structure/evidence.py`):
```python
"""근거 블록 — 층2 의 렌더 입력이자 층1 의 완료 판정.

원문 인용은 "해석이 다르다" 가 가능하지만 계산 내역은 그게 안 된다. 반박하려면
계산을 반박해야 한다. 그래서 이 층의 산출은 문장이 아니라 **수치 묶음**이다.

`scope` 가 빠지면 안 된다. 데이터가 좁은 건 결함이 아니지만 범위를 안 밝히고
일반화하는 건 결함이다.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from dartweave.structure.metrics import ClusterRow
from dartweave.structure.verdict import Verdict


@dataclass(frozen=True)
class Scope:
    industry: str
    companies: int
    disclosures: int
    fiscal_year: str
    boundary_ratio: float


@dataclass(frozen=True)
class Thresholds:
    """AC-12 — 임계값은 설정으로 정의되고 **출력에 명시**된다.

    코드에 매직넘버로 박히면 "왜 통과/반려됐는지" 를 산출물만 보고 알 수 없다.
    """

    min_corporate_resolution_rate: float
    max_boundary_ratio: float
    min_effect_size: float
    min_z: float
    sweep_tolerance: float


@dataclass(frozen=True)
class EvidenceBlock:
    lens: str
    include_types: list[str]
    objective: str
    resolution: float
    clusters: list[ClusterRow]
    modularity: float
    null_mean: float
    null_sd: float
    null_runs: int
    cpm_clusters: int
    cpm_delta: int
    sweep_holds: bool
    sweep_spread: float
    coef_sweep_holds: bool
    coef_sweep_spread: float
    corporate_resolution_rate: float
    scope: Scope
    thresholds: Thresholds
    verdict: Verdict


def to_json(block: EvidenceBlock) -> str:
    return json.dumps(
        {
            "lens": {"name": block.lens, "include_types": block.include_types},
            "algorithm": {
                "name": "leiden",
                "objective": block.objective,
                "resolution": block.resolution,
                "n_clusters": len(block.clusters),
            },
            "clusters": [
                {
                    "id": c.cluster_id,
                    "nodes": c.nodes,
                    "internal_edges": c.internal_edges,
                    "external_edges": c.external_edges,
                    "dependency_ratio": c.dependency_ratio,
                    "mean_supply_depth": c.mean_supply_depth,
                }
                for c in block.clusters
            ],
            "verification": {
                "edges": {
                    "corporate_resolution_rate": block.corporate_resolution_rate
                },
                "structure": {
                    "modularity": block.modularity,
                    "null_mean": block.null_mean,
                    "null_sd": block.null_sd,
                    "runs": block.null_runs,
                    "effect_size": round(block.modularity - block.null_mean, 6),
                    "cpm_clusters": block.cpm_clusters,
                    "cpm_delta": block.cpm_delta,
                },
                "stability": {
                    "resolution": {
                        "holds": block.sweep_holds,
                        "spread": block.sweep_spread,
                    },
                    "coefficients": {
                        "holds": block.coef_sweep_holds,
                        "spread": block.coef_sweep_spread,
                    },
                },
            },
            "scope": {
                "industry": block.scope.industry,
                "companies": block.scope.companies,
                "disclosures": block.scope.disclosures,
                "fiscal_year": block.scope.fiscal_year,
                "boundary_ratio": block.scope.boundary_ratio,
            },
            "thresholds": {
                "min_corporate_resolution_rate": (
                    block.thresholds.min_corporate_resolution_rate
                ),
                "max_boundary_ratio": block.thresholds.max_boundary_ratio,
                "min_effect_size": block.thresholds.min_effect_size,
                "min_z": block.thresholds.min_z,
                "sweep_tolerance": block.thresholds.sweep_tolerance,
            },
            "verdict": block.verdict.value,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/structure/test_evidence.py -v`
Expected: PASS — 7 passed

- [ ] **Step 5: 커밋**

```bash
git add src/dartweave/structure/evidence.py tests/structure/test_evidence.py
git commit -m "feat(structure): 근거 블록 직렬화 (층2 계약, scope 필수)"
```

---

### Task 11: LLM 해석 — 프롬프트 생성과 출력 검사 분리 (AC-9)

**Files:**
- Create: `src/dartweave/structure/interpret.py`
- Test: `tests/structure/test_interpret.py`

**Model**: sonnet

- [ ] **Step 1: 실패하는 테스트 작성**

**수정 후** (new file: `tests/structure/test_interpret.py`):
```python
import pytest

from dartweave.structure.interpret import (
    HallucinationDetected,
    allowed_tokens,
    build_prompt,
    check_output,
    interpret,
)

# 군집 번호도 숫자다. 실제로는 allowed_tokens 가 payload 의 `"id":0` 에서 뽑아주지만,
# 픽스처를 손으로 쓸 때는 빠뜨리기 쉽다 — 빠뜨리면 정상 문장이 '지어낸 숫자' 로 걸린다.
NUMBERS = {"26.1", "11", "287", "0"}
KNOWN = frozenset({"삼성전자", "태영건설", "건설공제조합", "현대자동차"})


def test_prompt_forbids_inventing_content():
    p = build_prompt('{"clusters": []}')
    assert "수치에 없는" in p


def test_output_using_only_given_numbers_passes():
    ok, extra = check_output(
        "군집 0은 노드 11개, 외부 엣지 287개, 의존도 26.1이다.", NUMBERS, KNOWN
    )
    assert ok and extra == []


def test_ordinary_korean_prose_is_not_flagged():
    """한국어는 교착어라 조사·어미가 붙는다.

    실측: 순진한 고유명사 정규식은 "11개다" 에서 '개다' 를, "병목이다" 에서
    '병목이다' 를 고유명사로 잡았다. 불용어 목록으로는 끝이 없어서,
    **기업명 사전 대조**로 바꿨다.
    """
    ok, extra = check_output("군집 0은 노드 11개다.", NUMBERS, KNOWN)
    assert ok, extra


def test_invented_number_is_caught():
    ok, extra = check_output("의존도는 99.9이다.", NUMBERS, KNOWN)
    assert not ok and "99.9" in extra


def test_invented_company_name_is_caught():
    """AC-9 — 수치뿐 아니라 고유명사도 지어내면 안 된다."""
    ok, extra = check_output("삼성전자가 병목이다.", NUMBERS, KNOWN)
    assert not ok and "삼성전자" in extra


def test_company_name_present_in_the_input_is_allowed():
    """입력에 있던 회사는 당연히 언급해도 된다 — 검사 대상은 '지어낸 것' 뿐이다."""
    ok, extra = check_output("태영건설이 병목이다.", NUMBERS | {"태영건설"}, KNOWN)
    assert ok, extra


def test_parent_name_nested_in_an_allowed_subsidiary_is_not_flagged():
    """한국 기업명은 접두 중첩이 흔하다 — 포스코/포스코케미칼, 한화/한화솔루션.

    입력에 자회사만 있는데 부모 이름이 그 안에 포함돼 있다고 '지어냈다' 고
    걸면, 정상 문장이 반려된다. 실측으로 재현된 오탐이다.
    """
    known = frozenset({"포스코", "포스코케미칼"})
    ok, extra = check_output("포스코케미칼이 병목이다.", {"포스코케미칼"}, known)
    assert ok, extra


def test_parent_mentioned_on_its_own_is_still_flagged():
    """구제는 자회사 이름에 가려진 경우만. 부모를 따로 끌어오면 여전히 환각이다."""
    known = frozenset({"포스코", "포스코케미칼"})
    ok, extra = check_output("포스코가 병목이다.", {"포스코케미칼"}, known)
    assert not ok and "포스코" in extra


def test_allowed_tokens_extracts_numbers_and_names_from_payload():
    toks = allowed_tokens('{"clusters":[{"id":0,"nodes":11}],"lens":{"name":"supply"}}')
    assert "11" in toks and "supply" in toks


def test_interpret_runs_the_check_automatically():
    """AC-9 — 검사가 '자동으로' 수행돼야 한다.

    검사를 별도 함수로만 두면 호출을 잊는 순간 조용히 통과한다.
    문장을 얻는 유일한 경로가 검사를 통과하는 경로여야 한다.
    """
    payload = '{"clusters":[{"id":0,"nodes":11}]}'
    assert interpret(payload, lambda _: "군집 0은 노드 11개다.", KNOWN)

    with pytest.raises(HallucinationDetected) as ei:
        interpret(payload, lambda _: "삼성전자가 노드 99개로 병목이다.", KNOWN)
    assert "삼성전자" in str(ei.value)


def test_interpret_passes_the_built_prompt_to_the_model():
    seen: list[str] = []

    def fake(prompt: str) -> str:
        seen.append(prompt)
        return "노드 11개."

    interpret('{"clusters":[{"id":0,"nodes":11}]}', fake, KNOWN)
    assert "수치에 없는" in seen[0]
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/structure/test_interpret.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dartweave.structure.interpret'`

- [ ] **Step 3: 구현**

**수정 후** (new file: `src/dartweave/structure/interpret.py`):
```python
"""LLM 해석 — 숫자를 만들지 않고 문장으로 옮기기만 한다.

환각을 사후에 잡는 게 아니라 **구조적으로 발생 못 하게** 한다. 계산은 엔진이 하고
LLM 은 이미 나온 표만 본다. 그리고 출력이 입력 토큰 집합을 벗어났는지 기계 검사한다.

모듈을 (프롬프트 생성 + 출력 검사) 로 쪼갠 이유: 모델 호출 없이 검사 함수만
단위 테스트하기 위해서다. 모델 응답 품질은 테스트 대상이 아니다.

**검사 방식이 두 갈래인 이유.** 숫자는 모호성이 없어 집합 대조로 끝난다. 그런데
고유명사를 정규식으로 잡으려던 첫 설계는 한국어에서 무너졌다 — 교착어라 조사·어미가
붙어서 "11개다" 의 '개다', "병목이다" 의 '병목이다' 가 고유명사로 잡혔다(실측).
불용어 목록을 늘리는 건 끝이 없다. 대신 **우리가 이미 가진 corpCode 실명 목록**과
대조한다: 사전에 있는 회사 이름이 출력에 있는데 입력에 없었다면, 그건 지어낸 것이다.
일반 산문 낱말은 사전에 없으므로 오탐이 나지 않는다(실측 확인).

**이 검사가 보장하는 범위를 정확히 말하면**: "실재하는 회사인데 입력에 없던 것" 을
잡는다. 사전에 아예 없는 완전 허구의 이름은 못 잡는다. 그래도 이게 유효한 이유는
현실적인 실패 모드가 **모델이 학습에서 기억한 진짜 회사를 끌어오는 것**이기 때문이다.
없는 회사를 창작하는 쪽은 프롬프트 금지로 막고, 남는 위험은 여기 적어 둔다.
"""
from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable

_NUMBER = re.compile(r"\d+(?:\.\d+)?")

# 2자 회사명은 일반어와 겹친다 — '대상'·'경방' 처럼. 3자 이상만 대조해서
# 오탐을 막는다. 대신 2자 회사명은 검출 사각지대로 남는다(알려진 한계).
MIN_ENTITY_LEN = 3

PROMPT_TEMPLATE = """아래는 그래프 분석 결과다. 이 수치만으로 설명하라.
수치에 없는 내용은 절대 추가하지 마라. 회사 이름을 지어내지 마라.

{payload}
"""


def allowed_tokens(payload_json: str) -> set[str]:
    """입력에 등장하는 숫자·이름. 출력은 이 안에서만 놀아야 한다."""
    toks: set[str] = set()

    def walk(node: object) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                toks.add(str(k))
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
        elif node is not None:
            toks.add(str(node))

    walk(json.loads(payload_json))
    numeric = {t for t in list(toks) if _NUMBER.fullmatch(t)}
    for t in list(numeric):
        toks.add(t.rstrip("0").rstrip(".") if "." in t else t)
    return toks


def build_prompt(payload_json: str) -> str:
    return PROMPT_TEMPLATE.format(payload=payload_json)


def check_output(
    text: str, allowed: set[str], known_entities: Iterable[str]
) -> tuple[bool, list[str]]:
    """출력에 입력 밖 숫자·기업명이 있으면 실패.

    `known_entities` 는 corpCode 실명 목록 (해소 사전의 키). 이게 있어야
    "지어낸 회사" 와 "그냥 한국어 낱말" 을 구분할 수 있다.
    """
    extra: list[str] = []
    for m in _NUMBER.findall(text):
        if m not in allowed and m.rstrip("0").rstrip(".") not in allowed:
            extra.append(m)
    for name in known_entities:
        if len(name) < MIN_ENTITY_LEN or name not in text or name in allowed:
            continue
        # 접두 중첩 구제: 허용된 더 긴 이름이 본문에 있고 그 안에 이 이름이
        # 들어 있으면, 부모 회사가 '등장한' 게 아니라 자회사 이름의 일부일 뿐이다.
        # 실측 오탐: 입력에 포스코케미칼만 있는데 '포스코' 가 지어낸 이름으로 걸렸다.
        if any(len(a) > len(name) and name in a and a in text for a in allowed):
            continue
        extra.append(name)
    return (not extra), extra


class HallucinationDetected(RuntimeError):
    """모델이 입력 수치 밖의 숫자·기업명을 만들어냈다."""


def interpret(
    payload_json: str,
    call_model: Callable[[str], str],
    known_entities: Iterable[str],
) -> str:
    """AC-9 — 해석문을 얻는 **유일한 경로**. 검사를 건너뛸 수 없다.

    `check_output` 을 따로 부르게 두면 호출을 잊는 순간 환각이 조용히 통과한다.
    모델 호출은 주입받는다 — 이 층은 어떤 모델을 쓰는지 알 필요가 없고,
    그 덕분에 검사 로직을 모델 없이 단위 테스트할 수 있다.
    """
    text = call_model(build_prompt(payload_json))
    ok, extra = check_output(text, allowed_tokens(payload_json), known_entities)
    if not ok:
        raise HallucinationDetected(
            f"입력에 없는 토큰 {len(extra)}건: {', '.join(extra[:10])}"
        )
    return text
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/structure/test_interpret.py -v`
Expected: PASS — 11 passed

- [ ] **Step 5: 커밋**

```bash
git add src/dartweave/structure/interpret.py tests/structure/test_interpret.py
git commit -m "feat(structure): LLM 해석 프롬프트 + 출력 토큰 검사 (환각 구조적 차단)"
```

---

### Task 12: 파이프라인 — 게이트 두 개가 앞을 막는다 (AC-12 · AC-14)

**Files:**
- Create: `src/dartweave/structure/pipeline.py`
- Test: `tests/structure/test_pipeline.py`

**Model**: sonnet

- [ ] **Step 1: 실패하는 테스트 작성**

**수정 후** (new file: `tests/structure/test_pipeline.py`):
```python
import pytest

from dartweave.structure.pipeline import (
    AnalysisConfig,
    QualityGateFailed,
    analyze,
)
from dartweave.structure.topology import BoundaryNotClosed
from dartweave.structure.verdict import Verdict

EDGES = [("A", "B", "INVESTS_IN"), ("B", "C", "INVESTS_IN"), ("C", "A", "INVESTS_IN")]
INTERIOR = {"A", "B", "C"}


def test_quality_gate_blocks_before_any_computation():
    """AC-12 — 미달이면 '일단 돌려보고 판단' 을 허용하지 않는다."""
    cfg = AnalysisConfig(min_corporate_resolution_rate=0.9)
    with pytest.raises(QualityGateFailed) as ei:
        analyze(EDGES, interior=INTERIOR, lens_name="governance",
                corporate_resolution_rate=0.6, config=cfg)
    assert "0.6" in str(ei.value) or "60" in str(ei.value)


def test_boundary_gate_blocks_topology_but_not_clustering():
    """D2 — 군집은 경계에 견디고 방향 지표는 못 견딘다."""
    cfg = AnalysisConfig(min_corporate_resolution_rate=0.0, max_boundary_ratio=0.0)
    with pytest.raises(BoundaryNotClosed):
        analyze(EDGES, interior={"A"}, lens_name="governance",
                corporate_resolution_rate=1.0, config=cfg)


def test_closed_graph_produces_an_evidence_block():
    cfg = AnalysisConfig(min_corporate_resolution_rate=0.0, max_boundary_ratio=0.0,
                         null_runs=3)
    block = analyze(EDGES, interior=INTERIOR, lens_name="governance",
                    corporate_resolution_rate=1.0, config=cfg)
    assert block.scope.boundary_ratio == 0.0
    assert isinstance(block.verdict, Verdict)


def test_lens_filters_edges_before_analysis():
    cfg = AnalysisConfig(min_corporate_resolution_rate=0.0, max_boundary_ratio=0.0,
                         null_runs=3)
    mixed = EDGES + [("A", "C", "SUPPLIES_TO")]
    block = analyze(mixed, interior=INTERIOR, lens_name="governance",
                    corporate_resolution_rate=1.0, config=cfg)
    assert block.include_types == sorted(["MAJOR_SHAREHOLDER_OF", "INVESTS_IN",
                                          "HOLDS_5PCT"])


def test_no_conclusion_is_returned_not_raised():
    """AC-10 — 결론 없음이 예외 경로가 아니다."""
    cfg = AnalysisConfig(min_corporate_resolution_rate=0.0, max_boundary_ratio=0.0,
                         null_runs=3)
    block = analyze(EDGES, interior=INTERIOR, lens_name="governance",
                    corporate_resolution_rate=1.0, config=cfg)
    assert block.verdict in set(Verdict)


def test_mismatched_evidence_length_is_rejected_loudly():
    """평행 리스트가 어긋나면 **가중치가 엉뚱한 엣지에 붙는다** — 조용히 넘기면 안 된다."""
    from dartweave.structure.weight import EdgeEvidence

    cfg = AnalysisConfig(min_corporate_resolution_rate=0.0, max_boundary_ratio=0.0)
    with pytest.raises(ValueError) as ei:
        analyze(EDGES, interior=INTERIOR, lens_name="governance",
                corporate_resolution_rate=1.0,
                evidence=[EdgeEvidence(True, False, 1, None, None)], config=cfg)
    assert "길이" in str(ei.value)


def test_coefficient_sweep_runs_only_when_evidence_is_supplied():
    """AC-8 — 근거 없이 계수를 흔들 수는 없다. '검사 안 함' 을 '버텼음' 으로 위장하지 않는다."""
    from dartweave.structure.weight import EdgeEvidence

    cfg = AnalysisConfig(min_corporate_resolution_rate=0.0, max_boundary_ratio=0.0,
                         null_runs=3)
    without = analyze(EDGES, interior=INTERIOR, lens_name="governance",
                      corporate_resolution_rate=1.0, config=cfg)
    assert without.coef_sweep_holds is False

    ev = [EdgeEvidence(True, False, 1, None, None) for _ in EDGES]
    with_ev = analyze(EDGES, interior=INTERIOR, lens_name="governance",
                      corporate_resolution_rate=1.0, evidence=ev, config=cfg)
    assert isinstance(with_ev.coef_sweep_holds, bool)


def test_thresholds_and_industry_reach_the_evidence_block():
    """AC-12 · AC-13 — 설정이 산출물까지 실려야 한다."""
    cfg = AnalysisConfig(min_corporate_resolution_rate=0.0, max_boundary_ratio=0.0,
                         null_runs=3, industry="건설")
    block = analyze(EDGES, interior=INTERIOR, lens_name="governance",
                    corporate_resolution_rate=1.0, config=cfg)
    assert block.scope.industry == "건설"
    assert block.thresholds.min_corporate_resolution_rate == 0.0
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/structure/test_pipeline.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dartweave.structure.pipeline'`

- [ ] **Step 3: 구현**

**수정 후** (new file: `src/dartweave/structure/pipeline.py`):
```python
"""analyze() — 게이트 두 개가 계산 앞을 막는다.

게이트를 뒤에 두면 이미 나온 결과를 보고 판단하게 되어 사후 합리화가 들어온다.
요구사항 결정 11의 *"일단 돌려보고 나중에 판단 금지"* 를 구조로 강제한다.

CLI 는 이 함수를 부르는 껍데기다 — 층0 의 run_stage.py 가 init_schema 를 무조건
호출해 DB 없이 아무 단계도 못 돌던 갭(CH-20260813-015)을 반복하지 않기 위해서다.
"""
from __future__ import annotations

from dataclasses import dataclass

from dartweave.structure.cluster import cluster, compare_objectives
from dartweave.structure.evidence import EvidenceBlock, Scope, Thresholds
from dartweave.structure.lens import resolve_lens, select_indices
from dartweave.structure.metrics import cluster_metrics
from dartweave.structure.nullmodel import degree_preserving_null
from dartweave.structure.project import boundary_of, project
from dartweave.structure.sensitivity import (
    DEFAULT_TOLERANCE,
    coefficient_sweep,
    resolution_sweep,
)
from dartweave.structure.topology import topology
from dartweave.structure.verdict import MIN_EFFECT, MIN_Z, decide
from dartweave.structure.weight import EdgeEvidence, edge_weights

OUTLIER_MULTIPLE = 2.0  # 최상위 의존도가 중앙값의 이 배를 넘으면 "편차 있음"


class QualityGateFailed(RuntimeError):
    """층0 품질이 임계 미만 — 그 위에서 계산한 의존도는 의미가 없다."""


@dataclass(frozen=True)
class AnalysisConfig:
    min_corporate_resolution_rate: float = 0.8
    max_boundary_ratio: float = 0.0
    resolution: float = 1.0
    cpm_resolution: float = 0.005
    null_runs: int = 20
    sweep_tolerance: float = DEFAULT_TOLERANCE
    fiscal_year: str = "2024"
    industry: str = "미지정"


def _has_outlier(ratios: list[float]) -> bool:
    if len(ratios) < 2:
        return False
    ordered = sorted(ratios, reverse=True)
    mid = ordered[len(ordered) // 2]
    return mid > 0 and ordered[0] >= mid * OUTLIER_MULTIPLE


def analyze(
    edges: list[tuple[str, str, str]],
    *,
    interior: set[str],
    lens_name: str,
    corporate_resolution_rate: float,
    evidence: list[EdgeEvidence] | None = None,
    config: AnalysisConfig | None = None,
) -> EvidenceBlock:
    """`evidence` 는 `edges` 와 **같은 순서의 평행 리스트**다.

    주면 가중 실행 + 겹2 계수 스윕(AC-8)이 돌고, 안 주면 무가중 실행된다.
    """
    cfg = config or AnalysisConfig()
    if evidence is not None and len(evidence) != len(edges):
        raise ValueError(
            f"evidence({len(evidence)}) 와 edges({len(edges)}) 길이가 다르다 — "
            "가중치가 엉뚱한 엣지에 붙는다."
        )

    # [G1] 품질 게이트 — 계산 전에 막는다.
    if corporate_resolution_rate < cfg.min_corporate_resolution_rate:
        raise QualityGateFailed(
            f"법인 해소율 {corporate_resolution_rate:.2f} < "
            f"임계 {cfg.min_corporate_resolution_rate:.2f} — 분석을 실행하지 않는다."
        )

    lens = resolve_lens(lens_name)
    idx = select_indices(edges, lens)
    kept = [edges[i] for i in idx]
    kept_ev = [evidence[i] for i in idx] if evidence is not None else None
    boundary = boundary_of(kept, interior)

    weights = edge_weights(kept_ev) if kept_ev is not None else None
    und = project(kept, undirected=True, weights=weights)
    nat = project(kept, undirected=False)

    # [G2] 경계 게이트 — 층위·중심성만 막는다. 군집은 경계에 견딘다.
    topo = topology(nat, boundary, max_boundary_ratio=cfg.max_boundary_ratio)

    clu = cluster(und, objective="modularity", resolution=cfg.resolution, seed=1)
    codes = list(und.vs["corp_code"])
    membership = dict(zip(codes, clu.membership))

    rows = cluster_metrics(kept, membership, depth=topo.depth)
    null = degree_preserving_null(und, runs=cfg.null_runs, seed=1)
    sweep = resolution_sweep(und, tolerance=cfg.sweep_tolerance)
    cmp_obj = compare_objectives(
        und, resolution=cfg.resolution, cpm_resolution=cfg.cpm_resolution
    )

    # AC-8 — 근거가 있을 때만 계수를 흔들 수 있다. 없으면 흔들 대상이 없으므로
    # "버텼다" 가 아니라 **검사하지 않았다** 로 두고 결론 판정에서 제외한다.
    if kept_ev is not None:
        coef = coefficient_sweep(
            kept, kept_ev, resolution=cfg.resolution, tolerance=cfg.sweep_tolerance
        )
        coef_holds, coef_spread = coef.holds, coef.spread
        stability_holds = sweep.holds and coef.holds
    else:
        coef_holds, coef_spread = False, 0.0
        stability_holds = sweep.holds

    verdict = decide(
        z=null.z,
        effect_size=null.effect_size,
        sweep_holds=stability_holds,
        has_outlier=_has_outlier([r.dependency_ratio for r in rows]),
    )

    return EvidenceBlock(
        lens=lens.name,
        include_types=sorted(lens.include),
        objective="modularity",
        resolution=cfg.resolution,
        clusters=rows,
        modularity=null.actual,
        null_mean=null.mean,
        null_sd=null.sd,
        null_runs=null.runs,
        cpm_clusters=cmp_obj["cpm_clusters"],
        cpm_delta=cmp_obj["delta"],
        sweep_holds=sweep.holds,
        sweep_spread=sweep.spread,
        coef_sweep_holds=coef_holds,
        coef_sweep_spread=coef_spread,
        corporate_resolution_rate=corporate_resolution_rate,
        scope=Scope(
            industry=cfg.industry,
            companies=len({v for e in kept for v in e[:2]}),
            disclosures=len(kept),
            fiscal_year=cfg.fiscal_year,
            boundary_ratio=boundary.ratio,
        ),
        thresholds=Thresholds(
            min_corporate_resolution_rate=cfg.min_corporate_resolution_rate,
            max_boundary_ratio=cfg.max_boundary_ratio,
            min_effect_size=MIN_EFFECT,
            min_z=MIN_Z,
            sweep_tolerance=cfg.sweep_tolerance,
        ),
        verdict=verdict,
    )
```

> **AC-12 의 미완 부분을 명시한다.** 요구사항은 *"해소율 → 재현율 순으로"* 검사하라고 하지만, 재현율·정밀도는 슬라이스 2(본문 LLM 추출)가 있어야 값이 생긴다. 그래서 G1 은 지금 **해소율만으로 동작**하고 재현율 검사는 값이 도착하면 같은 자리에 추가된다. 이 유예는 기술설계서가 `blocking` 으로 기록한 항목이며, 여기서 숨기지 않고 드러낸다.

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/structure/test_pipeline.py -v`
Expected: PASS — 8 passed

- [ ] **Step 5: 커밋**

```bash
git add src/dartweave/structure/pipeline.py tests/structure/test_pipeline.py
git commit -m "feat(structure): analyze() 파이프라인 (품질·경계 게이트가 계산 앞을 막음)"
```

---

### Task 13: 성질 테스트 — 구조 없는 그래프는 결론 없음

**Files:**
- Test: `tests/structure/test_properties.py`

**Model**: sonnet

- [ ] **Step 1: 성질 테스트 작성**

**수정 후** (new file: `tests/structure/test_properties.py`):
```python
"""성질 테스트 — 구조 분석에는 "정답" 이 없으므로 불변 성질을 검증한다."""
import random

import igraph as ig

from dartweave.structure.nullmodel import degree_preserving_null
from dartweave.structure.pipeline import AnalysisConfig, analyze
from dartweave.structure.verdict import Verdict


def _planted_blocks(k: int = 4, size: int = 8) -> list[tuple[str, str, str]]:
    """계획된 군집 구조 — 덩어리 k개가 다리로 느슨히 연결."""
    edges = []
    for b in range(k):
        members = [f"B{b}N{i}" for i in range(size)]
        for i in range(size):
            for j in range(i + 1, size):
                edges.append((members[i], members[j], "INVESTS_IN"))
        if b:
            edges.append((f"B{b-1}N0", members[0], "INVESTS_IN"))
    return edges


def test_planted_structure_beats_its_null():
    """실측 접지: 32노드 4블록에서 실제 0.7239 vs 귀무 0.2727 (효과 +0.4512)."""
    edges = _planted_blocks()
    g = ig.Graph.TupleList([(a, b) for a, b, _ in edges], directed=False)
    r = degree_preserving_null(g, runs=10, seed=1)
    assert r.actual > r.mean
    assert r.effect_size > 0.3
    assert r.swaps_failed == 0


def test_random_graph_yields_no_conclusion_not_a_crash():
    """무구조 입력에서 엔진이 죽지 않고 `결론 없음` 을 돌려줘야 한다 (AC-10).

    시드를 고정해야 결정적이다 — ER 효과크기는 시드에 따라 -0.013 ~ +0.020 을
    오가고, 임계(0.05)에 가깝게 튀는 draw 가 실제로 관측됐다.
    """
    ig.set_random_number_generator(random.Random(1))
    g = ig.Graph.Erdos_Renyi(n=40, m=120)
    edges = [
        (f"N{e.source}", f"N{e.target}", "INVESTS_IN") for e in g.es
    ]
    nodes = {v for e in edges for v in e[:2]}
    block = analyze(
        edges,
        interior=nodes,
        lens_name="governance",
        corporate_resolution_rate=1.0,
        config=AnalysisConfig(min_corporate_resolution_rate=0.0,
                              max_boundary_ratio=0.0, null_runs=5),
    )
    assert block.verdict in (Verdict.NO_CONCLUSION, Verdict.PARAMETER_DEPENDENT)


def test_degree_sequence_survives_shuffle():
    edges = _planted_blocks()
    g = ig.Graph.TupleList([(a, b) for a, b, _ in edges], directed=False)
    assert degree_preserving_null(g, runs=5, seed=1).degree_preserved


def test_effect_size_is_reported_alongside_z():
    """z 는 표준편차가 작으면 부풀려진다 — 효과크기를 함께 봐야 한다."""
    edges = _planted_blocks()
    g = ig.Graph.TupleList([(a, b) for a, b, _ in edges], directed=False)
    r = degree_preserving_null(g, runs=10, seed=1)
    assert hasattr(r, "z") and hasattr(r, "effect_size")
```

- [ ] **Step 2: 실행 확인**

Run: `uv run pytest tests/structure/test_properties.py -v`
Expected: PASS — 4 passed

- [ ] **Step 3: 커밋**

```bash
git add tests/structure/test_properties.py
git commit -m "test(structure): 성질 테스트 (계획된 구조 vs 무작위, 차수 보존)"
```

---

### Task 14: CLI 껍데기 + 실측 골든

**Files:**
- Create: `scripts/analyze_structure.py`
- Test: `tests/structure/test_cli.py`

**Model**: sonnet

- [ ] **Step 1: 실패하는 테스트 작성**

**수정 후** (new file: `tests/structure/test_cli.py`):
```python
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "analyze_structure.py"), *args],
        capture_output=True, text=True, cwd=ROOT,
    )


def test_missing_graph_file_exits_with_clear_message(tmp_path):
    r = _run("--graph", str(tmp_path / "nope.json"), "--lens", "governance")
    assert r.returncode == 2
    assert "찾을 수 없" in r.stderr or "not found" in r.stderr.lower()


def test_unknown_lens_lists_available(tmp_path):
    f = tmp_path / "g.json"
    f.write_text(json.dumps({"edges": [], "interior": []}), encoding="utf-8")
    r = _run("--graph", str(f), "--lens", "nope")
    assert r.returncode == 2 and "governance" in r.stderr


EDGES = [["A", "B", "INVESTS_IN"], ["B", "C", "INVESTS_IN"], ["C", "A", "INVESTS_IN"]]


def test_valid_run_emits_evidence_json(tmp_path):
    f = tmp_path / "g.json"
    f.write_text(json.dumps({"edges": EDGES, "interior": ["A", "B", "C"]}),
                 encoding="utf-8")
    r = _run("--graph", str(f), "--lens", "governance",
             "--min-resolution-rate", "0", "--null-runs", "3", "--industry", "건설")
    assert r.returncode == 0, r.stderr
    d = json.loads(r.stdout)
    assert d["scope"]["boundary_ratio"] == 0.0
    assert d["scope"]["industry"] == "건설"


def test_open_boundary_exits_with_its_own_code(tmp_path):
    """게이트마다 exit code 가 달라야 자동화가 원인을 구분한다."""
    f = tmp_path / "g.json"
    f.write_text(json.dumps({"edges": EDGES, "interior": ["A"]}), encoding="utf-8")
    r = _run("--graph", str(f), "--lens", "governance",
             "--min-resolution-rate", "0", "--null-runs", "3")
    assert r.returncode == 4 and "경계 게이트" in r.stderr


def test_quality_gate_exits_with_code_three(tmp_path):
    f = tmp_path / "g.json"
    f.write_text(json.dumps({"edges": EDGES, "interior": ["A", "B", "C"]}),
                 encoding="utf-8")
    r = _run("--graph", str(f), "--lens", "governance",
             "--resolution-rate", "0.1", "--min-resolution-rate", "0.9")
    assert r.returncode == 3 and "품질 게이트" in r.stderr


def test_evidence_in_payload_enables_coefficient_sweep(tmp_path):
    """AC-8 이 CLI 경로에서도 실제로 돈다."""
    ev = [{"is_structured": True, "cross_confirmed": False, "mention_count": 1}
          for _ in EDGES]
    f = tmp_path / "g.json"
    f.write_text(json.dumps({"edges": EDGES, "interior": ["A", "B", "C"],
                             "evidence": ev}), encoding="utf-8")
    r = _run("--graph", str(f), "--lens", "governance",
             "--min-resolution-rate", "0", "--null-runs", "3")
    assert r.returncode == 0, r.stderr
    assert "coefficients" in json.loads(r.stdout)["verification"]["stability"]
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/structure/test_cli.py -v`
Expected: FAIL — 스크립트 없음 (returncode 2 아님)

- [ ] **Step 3: 구현**

**수정 후** (new file: `scripts/analyze_structure.py`):
```python
"""구조 분석 CLI — analyze() 를 부르는 껍데기.

로직은 전부 `dartweave.structure.pipeline` 에 있다. CLI 가 두꺼워지면 층2가
같은 로직을 재작성하게 되고, 실행 환경에 로직이 묶이면 층0의 run_stage.py 갭이
반복된다.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dartweave.structure.evidence import to_json
from dartweave.structure.lens import LENSES
from dartweave.structure.pipeline import AnalysisConfig, QualityGateFailed, analyze
from dartweave.structure.topology import BoundaryNotClosed
from dartweave.structure.weight import EdgeEvidence

GRAPH_SHAPE = "{edges: [[a,b,type]], interior: [], evidence?: [{...}]}"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--graph", required=True, help=GRAPH_SHAPE)
    p.add_argument("--lens", required=True, choices=sorted(LENSES), metavar="LENS")
    p.add_argument("--resolution-rate", type=float, default=1.0)
    p.add_argument("--min-resolution-rate", type=float, default=0.8)
    p.add_argument("--max-boundary-ratio", type=float, default=0.0)
    p.add_argument("--null-runs", type=int, default=20)
    p.add_argument("--industry", default="미지정", help="AC-13 분석 범위 표기")
    p.add_argument("--fiscal-year", default="2024")

    try:
        args = p.parse_args(argv)
    except SystemExit:
        print(f"사용 가능한 렌즈: {', '.join(sorted(LENSES))}", file=sys.stderr)
        return 2

    path = Path(args.graph)
    if not path.exists():
        print(f"그래프 파일을 찾을 수 없습니다: {path}", file=sys.stderr)
        return 2

    payload = json.loads(path.read_text(encoding="utf-8"))
    edges = [tuple(e) for e in payload["edges"]]
    interior = set(payload["interior"])
    raw_ev = payload.get("evidence")
    evidence = (
        [
            EdgeEvidence(
                is_structured=bool(r["is_structured"]),
                cross_confirmed=bool(r["cross_confirmed"]),
                mention_count=int(r["mention_count"]),
                share_pct=r.get("share_pct"),
                observed_precision=r.get("observed_precision"),
            )
            for r in raw_ev
        ]
        if raw_ev
        else None
    )

    cfg = AnalysisConfig(
        min_corporate_resolution_rate=args.min_resolution_rate,
        max_boundary_ratio=args.max_boundary_ratio,
        null_runs=args.null_runs,
        industry=args.industry,
        fiscal_year=args.fiscal_year,
    )
    try:
        block = analyze(
            edges,
            interior=interior,
            lens_name=args.lens,
            corporate_resolution_rate=args.resolution_rate,
            evidence=evidence,
            config=cfg,
        )
    except QualityGateFailed as e:
        print(f"[품질 게이트] {e}", file=sys.stderr)
        return 3
    except BoundaryNotClosed as e:
        print(f"[경계 게이트] {e}", file=sys.stderr)
        return 4

    print(to_json(block))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/structure/test_cli.py -v`
Expected: PASS — 6 passed

- [ ] **Step 5: 전체 스위트 확인**

Run: `uv run pytest -q`
Expected: PASS — 기존 148 + 신규 전부 통과

- [ ] **Step 6: 커밋**

```bash
git add scripts/analyze_structure.py tests/structure/test_cli.py
git commit -m "feat(structure): 분석 CLI (게이트별 exit code 분리)"
```

---

## 2. 위험 코드 지점

기술설계서 §6 의 위험 카테고리를 코드 위치에 매핑한다.

- `src/dartweave/structure/pipeline.py:AnalysisConfig` — **side-effect**: `min_corporate_resolution_rate`·`max_boundary_ratio` 가 검출 여부를 직접 좌우한다. 느슨하면 무의미한 결론이 통과하고, 빡빡하면 정상 데이터가 거부된다 | mitigation: 설정으로 노출 + 근거 블록에 실제 사용값 기록. 실측 기준선(법인 해소율 60%, 경계 0%) 을 문서에 남김
- `src/dartweave/structure/nullmodel.py:degree_preserving_null` — **side-effect**: `runs` 가 `sd` 를 좌우하고 `sd` 가 `z` 를 좌우한다. 반복이 적으면 z 가 요동친다 | mitigation: `runs` 를 출력에 명시(AC-5) + `effect_size` 병기로 z 단독 오독 차단
- `src/dartweave/structure/nullmodel.py:_to_nx` — **breaking**: 완전 무작위 셔플로 바꾸면 귀무 모듈러리티가 부당하게 낮아져 **모든 그래프가 "구조 있음" 으로 판정**된다 | mitigation: `degree_preserved` 플래그를 결과에 담고 성질 테스트로 고정
- `src/dartweave/structure/verdict.py:decide` — **breaking**: 판정 순서를 바꾸면(스윕 검사를 뒤로) 불안정한 결론이 채택된다 | mitigation: 순서를 주석으로 고정 + 세 상태 각각 테스트
- `src/dartweave/structure/verdict.py:Verdict` — **breaking**: `NO_CONCLUSION` 을 예외로 바꾸면 AC-10 위반이고 호출부가 결론 없음을 실패로 취급하게 된다 | mitigation: 세 상태 동등 반환 테스트
- `src/dartweave/structure/topology.py:topology` — **breaking**: 경계 게이트를 풀면 출차수 1위가 뒤바뀐 채로 보고된다(실측: 한화→태영건설) | mitigation: `BoundaryNotClosed` 예외 + 게이트 우회 경로 없음
- `src/dartweave/structure/lens.py:Lens` — **breaking**: 중간 가중치 필드를 추가하면 AC-1 위반이고 *"왜 0.1인데요"* 에 답할 수 없게 된다 | mitigation: `vars(lens)` 필드 집합 테스트로 고정
- `src/dartweave/structure/metrics.py:ClusterRow` — **breaking**: 의미 라벨 필드를 추가하면 결론이 데이터가 아니라 라벨에서 나온다(AC-4) | mitigation: 필드 집합 테스트로 고정
- `src/dartweave/structure/cluster.py:cluster` — **side-effect**: `seed` 없이 돌리면 실행마다 군집이 달라져 골든 테스트가 흔들린다 | mitigation: 파이프라인이 항상 `seed=1` 주입 + 재현성 테스트
- `src/dartweave/structure/interpret.py:MIN_ENTITY_LEN` — **side-effect**: 2자 회사명(`대상`·`경방`·`한화`)은 일반어와 겹쳐 대조에서 제외된다 → **2자 기업명 환각은 못 잡는다**(알려진 사각지대). 낮추면 "분석 **대상**은" 같은 정상 문장이 반려된다 | mitigation: 하한을 상수로 노출 + 사각지대를 주석·본 항목에 명시. 실제 환각 표적은 대부분 3자 이상(삼성전자·태영건설·건설공제조합)
- `src/dartweave/structure/interpret.py:check_output` — **side-effect**: `known_entities` 가 비면 기업명 검사가 **통째로 무력화**되는데 예외 없이 통과한다 | mitigation: 호출부(층2·스크립트)가 해소 사전 키를 항상 넘기도록 계약에 명시. 빈 목록은 "검사 안 함" 이지 "통과" 가 아니다
- `src/dartweave/structure/interpret.py:interpret` — **breaking**: `check_output` 을 우회해 모델 텍스트를 직접 쓰는 경로가 생기면 AC-9 가 무력화된다 | mitigation: 해석문을 얻는 공개 경로를 `interpret()` 하나로 유지. 위반 시 `HallucinationDetected` 로 **중단**하고 텍스트를 돌려주지 않음
- `src/dartweave/structure/weight.py:MIN_WEIGHT` — **side-effect**: 하한이 없으면 가중치 0 엣지를 Leiden 이 무시해 그래프가 조용히 끊긴다 | mitigation: 양수 보장 테스트
- `src/dartweave/structure/sensitivity.py:COEFFICIENT_CASES` — **side-effect**: 계수 축을 전수 조합하면 폭발한다(4축 × 각 3값 = 81회 클러스터링). 현재는 **축별 독립 5케이스**이며 계수 간 상호작용은 검사하지 않는다 | mitigation: 케이스 목록을 상수로 노출하고 근거 블록에 `label` 을 실어 무엇을 검사했는지/안 했는지 드러냄. 상호작용은 범위 밖으로 명시
- `src/dartweave/structure/pipeline.py:analyze` — **breaking**: `evidence` 와 `edges` 는 평행 리스트다. 렌즈 필터를 엣지에만 적용하면 **가중치가 엉뚱한 엣지에 붙고**, 그 오염은 군집 결과까지 조용히 흘러간다 | mitigation: `select_indices()` 로 같은 인덱스를 양쪽에 적용 + 길이 불일치 시 `ValueError`
- `src/dartweave/structure/verdict.py:MIN_EFFECT` — **side-effect**: 0.02 로 두면 무구조 ER 그래프가 통과한다(실측 상한 +0.020). 반대로 과하게 올리면 진짜 신호(+0.1305)를 놓친다 | mitigation: 잡음 상한·실측 신호 양쪽을 고정한 테스트 2건

### 계획 작성 중 실측으로 드러난 API 함정 3건

층0 교훈("계획서의 가정을 fixture 가 못 잡는다")을 적용해 계획 단계에서 실제로 호출해봤고, 초안의 결함 3건이 잡혔다. 구현자는 아래를 그대로 지킬 것.

- `src/dartweave/structure/project.py:project` — **breaking**: `to_undirected(combine_edges="sum")` 는 문자열 속성 `type` 에서 `TypeError: product can only be invoked on numeric attributes` 로 죽는다 | mitigation: `{"weight": "sum", "type": "first"}` dict 형태 고정 (weight 부재 시에도 안전함을 실측 확인)
- `src/dartweave/structure/nullmodel.py:degree_preserving_null` — **breaking**: `nx.NetworkXAlgorithmError` 는 `nx.NetworkXError` 의 하위가 **아니다**(형제 예외). 하나만 잡으면 4노드 미만 그래프에서 통째로 터진다 | mitigation: 둘 다 잡고 `swaps_failed` 로 노출
- `src/dartweave/structure/cluster.py:cluster` — **race**: `ig.set_random_number_generator` 는 **프로세스 전역**이다. 민감도 스윕이나 귀무 반복을 병렬화하면 시드가 경합해 재현성이 깨진다 | mitigation: 현재는 단일 프로세스 순차 실행 유지. 병렬화 시 프로세스 분리 필수 (스레드 불가)

> 세 카테고리(`side-effect` · `breaking` · `race`) 모두 위에 실제 지점이 있다.

### 기술설계 §6 의 `blocking` 2건 처리 상태

- **층0 품질 지표 미완** — 재현율·정밀도는 슬라이스 2 소관. G1 은 **해소율만으로 동작**하고 재현율 검사는 값이 도착하면 같은 자리에 추가된다. Task 12 본문에 명시했다. **미해결 — 슬라이스 2로 이월.**
- **해소율 자연인/법인 미분리** — G1 활성의 선행조건이었고 **해소됨** (커밋 #38, `resolve/classify.py`). 실측 법인 해소율 60.0%. 따라서 `min_corporate_resolution_rate` 기본값 0.8 은 **현재 실데이터로는 G1 을 통과하지 못한다** — 의도된 동작이다(엔티티 별칭 사전으로 해소율을 올리는 게 먼저지, 임계를 낮추는 게 아니다).

---

## 3. 롤백 전략

- **Code**: 태스크마다 원자 커밋. `git revert <SHA>` 또는 `git reset --hard <Task 1 직전 SHA>` 로 패키지 통째 제거 가능
- **층0 영향 없음**: 본 계획은 `src/dartweave/structure/` 신규 패키지만 만든다. 층0 코드는 **읽기만** 하므로 롤백해도 층0 은 무손상
- **데이터**: 분석은 읽기 전용. `data/*.json` 은 입력이며 변경되지 않는다
- **의존성**: `igraph`·`networkx` 는 이미 설치·검증됨(경계 실험에서 실사용). 롤백 시에도 제거 불필요

---

## 변경이력

<!-- change-history skill auto-appends entries here, oldest first -->

### [2026-08-14 —] [구현계획서-수정]
- **id**: CH-20260814-003
- **이유**: 층1 구조 분석 엔진 구현계획서 최초 생성. 기술설계서(CH-20260814-002) 확정 + G1 게이트 선행조건(해소율 자연인/법인 분리, 커밋 #38) 해소로 착수 가능해짐
- **무엇이**: `structure-analysis-engine-implementation-plan.md` 전체 — 14 task · §2 위험 코드 지점 19건 · §3 롤백
- **영향범위**: 신규 파일만 생성(`src/dartweave/structure/` 12모듈 + `scripts/analyze_structure.py` + `tests/structure/` 14파일). **기존 코드 수정 0건** — 층0은 읽기만 하므로 기존 148 테스트에 영향 없음
- **연관 항목**: CH-20260814-001 (AC-14 신설), CH-20260814-002 (기술설계 확정)

#### 작성 중 실측으로 잡은 결함 5건

층0의 교훈("계획서의 가정을 fixture 가 못 잡는다")을 적용해, 계획이 쓴 API 를 **실제로 호출해봤다**. 초안의 결함 5건이 나왔고 전부 계획에 반영했다.

| # | 결함 | 실측 근거 |
|---|---|---|
| P1 | `to_undirected(combine_edges="sum")` 이 문자열 속성 `type` 에서 죽음 | `TypeError: product can only be invoked on numeric attributes` |
| P2 | `NetworkXAlgorithmError` 가 `NetworkXError` 의 **하위가 아님**(형제) → 4노드 미만 그래프에서 통째로 터짐 | `issubclass(...) == False`, 삼각형에서 `NetworkXError` 발생 |
| P3 | `MIN_EFFECT=0.02` 가 무구조 ER 그래프 잡음(+0.0199)과 겹침 | 시드별 ER 효과크기 -0.013 ~ +0.020 → 임계 0.05 로 상향 |
| P4 | 한국어 교착어 특성으로 고유명사 정규식 붕괴 | "11개다"→'개다', "병목이다"→'병목이다' 오탐 → **기업명 사전 대조**로 설계 변경 |
| P5 | `__import__("random")` 인라인 해킹 | 정식 모듈 임포트로 교정 |

#### verifying-spec 이 잡은 사양 커버리지 구멍 5건

| AC | 구멍 | 조치 |
|---|---|---|
| AC-8 | 겹2 계수 스윕 **함수 자체가 없었음** (해상도 스윕만 있었음) | `coefficient_sweep()` + `COEFFICIENT_CASES` 5케이스 신설 (Task 8) |
| AC-9 | `interpret.py` 를 아무도 호출 안 해 검사가 "자동" 이 아니었음 | `interpret()` 합성 — 문장을 얻는 유일한 경로가 검사를 통과하는 경로 (Task 11) |
| AC-12 | 임계값이 산출물에 안 실림 | `Thresholds` 신설 → 근거 블록에 노출 (Task 10) |
| AC-13 | 분석 범위에 **산업군** 누락 | `Scope.industry` 추가 (Task 10) |
| AC-2 | 가중/무가중이 실제로 다른지 확인하는 테스트 없음 | 실측(2군집→3군집) 기반 테스트 추가 (Task 4) |

#### 기술설계 대비 의도적 편차 1건

`centrality.py` 를 별도 모듈로 두지 않고 `topology.py` 에 합쳤다. 둘 다 방향 그래프에서 나오고 **똑같이 G2 경계 게이트에 걸리므로**, 분리하면 게이트를 두 곳에 중복 구현하게 되고 한쪽만 풀리는 사고가 난다. 모듈 13 → 12 + CLI.

#### 미해결 — 슬라이스 2로 이월

- **G1 의 재현율 검사 미활성**: 재현율·정밀도는 본문 LLM 추출(슬라이스 2)이 있어야 값이 생긴다. 지금은 **해소율만으로** G1 이 동작한다. 기술설계 §6 이 `blocking` 으로 기록한 항목이며 Task 12 본문에 명시했다.
- **`min_corporate_resolution_rate` 기본값 0.8 은 현재 실데이터(법인 해소율 60.0%)로 통과하지 못한다.** 의도된 동작 — 임계를 낮추는 게 아니라 `entity_alias` 사전으로 해소율을 올리는 게 먼저다.
- **2자 기업명 환각 사각지대**: `MIN_ENTITY_LEN=3` 이라 `대상`·`경방`·`한화` 는 검사에서 빠진다. 낮추면 "분석 **대상**은" 같은 정상 문장이 반려된다.
