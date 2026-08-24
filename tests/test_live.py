"""조회 계층 — 물어볼 때 그 회사 것만."""
import time

from dartweave.dart.live import Cached, neighbours


def test_cache_expires(tmp_path):
    """조회용의 값은 최신이라는 데 있다 — 캐시가 오래되면 그 값이 사라진다."""
    p = tmp_path / "x.json"
    p.write_text("{}", encoding="utf-8")
    assert Cached(p, ttl=3600).fresh
    assert not Cached(p, ttl=0).fresh


def test_missing_cache_is_not_fresh(tmp_path):
    assert not Cached(tmp_path / "없음.json").fresh


def test_neighbours_ignore_direction():
    """노출은 방향을 안 가린다 — A 가 B 를 가졌든 B 가 A 를 가졌든 엮인 건 같다."""
    edges = [("A", "B", "x"), ("C", "A", "x"), ("B", "D", "x")]
    assert neighbours(edges, "A", hops=1) == {"B": 1, "C": 1}
    assert neighbours(edges, "A", hops=2) == {"B": 1, "C": 1, "D": 2}


def test_neighbours_excludes_self_and_handles_isolation():
    assert neighbours([("A", "B", "x")], "A") == {"B": 1}
    assert neighbours([("A", "B", "x")], "Z") == {}


def test_hop_distance_is_the_shortest_one():
    """두 경로로 닿으면 짧은 쪽을 쓴다 — 안 그러면 이웃이 멀어 보인다."""
    edges = [("A", "B", "x"), ("A", "C", "x"), ("C", "B", "x")]
    assert neighbours(edges, "A", hops=2)["B"] == 1
