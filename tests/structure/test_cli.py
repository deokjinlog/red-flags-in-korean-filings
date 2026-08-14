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


def test_open_boundary_still_emits_clustering_by_default(tmp_path):
    """경계가 열려도 군집은 나온다 — 실데이터 경계 비율이 48.6% 라 통째 거부는 무용지물."""
    f = tmp_path / "g.json"
    f.write_text(json.dumps({"edges": EDGES, "interior": ["A"]}), encoding="utf-8")
    r = _run("--graph", str(f), "--lens", "governance",
             "--min-resolution-rate", "0", "--null-runs", "3")
    assert r.returncode == 0, r.stderr
    d = json.loads(r.stdout)
    assert d["topology_computed"] is False
    assert d["scope"]["boundary_ratio"] > 0


def test_require_topology_exits_with_its_own_code(tmp_path):
    """게이트마다 exit code 가 달라야 자동화가 원인을 구분한다."""
    f = tmp_path / "g.json"
    f.write_text(json.dumps({"edges": EDGES, "interior": ["A"]}), encoding="utf-8")
    r = _run("--graph", str(f), "--lens", "governance", "--require-topology",
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
