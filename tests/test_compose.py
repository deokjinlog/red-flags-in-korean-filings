import re
from pathlib import Path

COMPOSE = Path(__file__).resolve().parents[1] / "docker-compose.yml"


def _text() -> str:
    return COMPOSE.read_text(encoding="utf-8")


def test_required_services_present():
    t = _text()
    for svc in ("neo4j:", "postgres:"):
        assert svc in t, f"{svc} 서비스 정의 누락"


def test_ports_do_not_collide_with_existing_stack():
    """docs-rag(5433) · cogito(5434) · ga4(5436) · docs-rag-api(8002) 와 겹치면 안 됨."""
    published = set(re.findall(r'"(\d+):\d+"', _text()))
    forbidden = {"5433", "5434", "5436", "8002", "6333", "6334", "5672", "15672"}
    assert not (published & forbidden), f"포트 충돌: {published & forbidden}"


def test_gds_plugin_declared():
    assert "graph-data-science" in _text(), "GDS 플러그인 선언 누락"
