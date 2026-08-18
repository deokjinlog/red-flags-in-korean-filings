"""신호 검정 실행기 — 특징 계산이 그래프 구조와 맞는가.

검정 자체(순열)는 `test_signal.py` 가 본다. 여기서는 **어떤 회사가 신호군에 들어가는가**
를 고정한다. 신호군 정의가 틀리면 검정이 아무리 정확해도 엉뚱한 질문에 답하게 된다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from run_signal_test import build_features  # noqa: E402

R = "INVESTS_IN"


def test_circular_holding_is_detected_for_members_only():
    """고리에 낀 회사만 신호군이다 — 옆에 붙어 있다고 낀 게 아니다."""
    edges = [("a", "b", R), ("b", "c", R), ("c", "a", R), ("z", "a", R)]
    _, f = build_features(edges, chokepoints=set())
    assert f["circular"] == {"a", "b", "c"}


def test_mutual_holding_is_separate_from_circular():
    """상호 보유(길이 2)를 순환출자로도 세면 두 신호가 같은 걸 가리키게 된다."""
    edges = [("a", "b", R), ("b", "a", R)]
    _, f = build_features(edges, chokepoints=set())
    assert f["mutual"] == {"a", "b"} and f["circular"] == set()


def test_chokepoint_proximity_ignores_direction():
    """위험은 출자 방향을 안 가린다 — 소유하든 소유당하든 얽힌 건 같다."""
    edges = [("h", "a", R), ("a", "b", R)]
    _, f = build_features(edges, chokepoints={"h"}, hops=2)
    assert "a" in f["choke"] and "b" in f["choke"]


def test_chokepoint_itself_is_not_counted_as_near_itself():
    edges = [("h", "a", R)]
    _, f = build_features(edges, chokepoints={"h"}, hops=2)
    assert "h" not in f["choke"]


def test_far_company_is_not_near_the_chokepoint():
    edges = [("h", "a", R), ("a", "b", R), ("b", "c", R)]
    _, f = build_features(edges, chokepoints={"h"}, hops=2)
    assert "c" not in f["choke"]


def test_every_node_appears_in_the_universe():
    """대상 목록이 빠지면 대조군이 잘못 만들어진다."""
    edges = [("a", "b", R), ("c", "d", R)]
    nodes, _ = build_features(edges, chokepoints=set())
    assert set(nodes) == {"a", "b", "c", "d"}
