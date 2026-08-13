---
commit_policy: per-task
---

# 이중 출처 신뢰 그래프 (슬라이스 1 — 정형 전용) 구현계획서

> **다음 단계 안내**: 이 계획을 task-by-task 로 실행하려면 `subagent-driven` (보조 에이전트 모드, 13+ task 권장) 또는 `executing-plans` (인라인 모드) 를 사용하세요. 각 step 은 체크박스 (`- [ ]`) 형식이라 진행 상황 추적이 가능합니다.

**Goal:** 정형 API만으로 신뢰 등급이 붙은 관계 그래프를 세우고, **LLM 없이 1급 모순(정형↔정형 불일치)을 검출**한다.

**Architecture:** DART OpenAPI → 대상 선정 → 공시 수집 → 정형 관계 파싱 → Neo4j 멱등 적재 → 시점 스코프 분리 → 교차확인 → `evidence_weight` 파생 → 모순 A 검출 → 엣지 내보내기. 원장·상태는 Postgres, 그래프는 Neo4j. 각 단계는 독립 실행 + 체크포인트 재개.

**Tech Stack:** Python 3.13+ (uv) · httpx · SQLAlchemy 2.x · psycopg 3 · neo4j-driver · pytest · Docker Compose (Neo4j 5 + GDS, Postgres 16)

**Spec inputs:**
- `dual-source-trust-graph-requirements.md` — 결정 1·2·3·5·6·7·8 / AC-1·2·3·5·6·8·9·11
- `dual-source-trust-graph-tech-design.md` — D1(Neo4j+GDS) · D3(별도 스택) · D4(스크립트+체크포인트) · D5(weight 파생) · D8(포트)

**슬라이스 경계 (본 계획에서 제외 — 슬라이스 2)**: 본문 LLM 추출 · 재현율/정밀도 측정 · 공급 엣지 교차확인 · 모순 B/C/D

> ⚠️ **엔티티 해소는 슬라이스 1에 포함된다** (계획 작성 중 발견). 정형 API도 관계 상대를 **이름 문자열로만** 준다 — 「최대주주 현황」의 `nm`, 「타법인 출자현황」의 `inv_prm` 에 `corp_code` 가 없다. 즉 LLM 추출과 무관하게 **정형 데이터만으로도 이름→코드 해소가 필요**하다. 슬라이스 2로 미룰 수 없다.

---

## 1. 단계별 작업

### Task 1: 프로젝트 스캐폴딩 + 설정

**Files:**
- Create: `pyproject.toml` · `.gitignore` · `.env.example` · `src/dartweave/__init__.py` · `src/dartweave/config.py`
- Test: `tests/test_config.py`

**Model**: haiku

- [ ] **Step 1: git 저장소 초기화**

```bash
cd /home/djchoi/deokjinlog/dartweave && git init && git branch -M main
```
Expected: `Initialized empty Git repository`

- [ ] **Step 2: 실패하는 테스트 작성**

**수정 후** (new file: `tests/test_config.py`):
```python
import os
from dartweave.config import Settings


def test_defaults_when_env_absent(monkeypatch):
    for key in ("DART_API_KEY", "PG_PORT", "NEO4J_BOLT_PORT", "DATA_DIR"):
        monkeypatch.delenv(key, raising=False)
    s = Settings.from_env()
    assert s.pg_port == 5435
    assert s.neo4j_bolt_port == 7687
    assert s.dart_api_key is None


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("DART_API_KEY", "k" * 40)
    monkeypatch.setenv("PG_PORT", "6000")
    s = Settings.from_env()
    assert s.dart_api_key == "k" * 40
    assert s.pg_port == 6000


def test_require_api_key_raises_when_missing(monkeypatch):
    monkeypatch.delenv("DART_API_KEY", raising=False)
    s = Settings.from_env()
    try:
        s.require_api_key()
    except RuntimeError as e:
        assert "DART_API_KEY" in str(e)
    else:
        raise AssertionError("expected RuntimeError")
```

- [ ] **Step 3: 실패 확인**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dartweave'`

- [ ] **Step 4: pyproject 작성**

**수정 후** (new file: `pyproject.toml`):
```toml
[project]
name = "dartweave"
version = "0.1.0"
description = "DART 공시 이중 출처 신뢰 그래프"
requires-python = ">=3.13"
dependencies = [
    "httpx>=0.28",
    "sqlalchemy>=2.0",
    "psycopg[binary]>=3.2",
    "neo4j>=5.28",
    "python-dotenv>=1.0",
]

[dependency-groups]
dev = ["pytest>=8.0"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/dartweave"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
```

- [ ] **Step 5: config 구현**

**수정 후** (new file: `src/dartweave/config.py`):
```python
"""환경 설정. 매직넘버는 전부 여기로 모은다."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

DART_BASE_URL = "https://opendart.fss.or.kr/api"


@dataclass(frozen=True)
class Settings:
    dart_api_key: str | None
    pg_host: str
    pg_port: int
    pg_db: str
    pg_user: str
    pg_password: str
    neo4j_bolt_port: int
    neo4j_user: str
    neo4j_password: str
    data_dir: Path

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            dart_api_key=os.getenv("DART_API_KEY") or None,
            pg_host=os.getenv("PG_HOST", "localhost"),
            pg_port=int(os.getenv("PG_PORT", "5435")),
            pg_db=os.getenv("PG_DB", "dartweave"),
            pg_user=os.getenv("PG_USER", "dartweave"),
            pg_password=os.getenv("PG_PASSWORD", "dartweave"),
            neo4j_bolt_port=int(os.getenv("NEO4J_BOLT_PORT", "7687")),
            neo4j_user=os.getenv("NEO4J_USER", "neo4j"),
            neo4j_password=os.getenv("NEO4J_PASSWORD", "dartweave1"),
            data_dir=Path(os.getenv("DATA_DIR", "./data")),
        )

    @property
    def pg_dsn(self) -> str:
        return (
            f"postgresql+psycopg://{self.pg_user}:{self.pg_password}"
            f"@{self.pg_host}:{self.pg_port}/{self.pg_db}"
        )

    @property
    def neo4j_uri(self) -> str:
        return f"bolt://localhost:{self.neo4j_bolt_port}"

    def require_api_key(self) -> str:
        """실 API 호출 직전에만 부른다. fixture 테스트는 이걸 안 탄다."""
        if not self.dart_api_key:
            raise RuntimeError(
                "DART_API_KEY 가 없습니다. opendart.fss.or.kr 에서 발급 후 .env 에 넣어주세요."
            )
        return self.dart_api_key
```

**수정 후** (new file: `src/dartweave/__init__.py`):
```python
__all__ = ["config"]
```

**수정 후** (new file: `.env.example`):
```bash
# opendart.fss.or.kr 에서 무료 발급 (40자리)
DART_API_KEY=

PG_HOST=localhost
PG_PORT=5435
PG_DB=dartweave
PG_USER=dartweave
PG_PASSWORD=dartweave

NEO4J_BOLT_PORT=7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=dartweave1

DATA_DIR=./data
```

**수정 후** (new file: `.gitignore`):
```gitignore
.venv/
__pycache__/
*.pyc
.env
data/
.pytest_cache/
```

- [ ] **Step 6: 의존성 설치 + 테스트 통과 확인**

Run: `cd /home/djchoi/deokjinlog/dartweave && uv sync && uv run pytest tests/test_config.py -v`
Expected: PASS — 3 passed

- [ ] **Step 7: 커밋**

```bash
git add pyproject.toml .gitignore .env.example src tests
git commit -m "feat: 프로젝트 스캐폴딩 + 환경 설정"
```

---

### Task 2: Docker 스택 정의 (기동은 사용자가)

**Files:**
- Create: `docker-compose.yml`
- Test: `tests/test_compose.py`

**Model**: haiku

> ⚠️ **컨테이너를 자동 기동하지 않는다.** 계획은 정의와 검증 테스트까지만 하고, `docker compose up` 은 사용자가 직접 실행한다.

- [ ] **Step 1: 실패하는 테스트 작성**

**수정 후** (new file: `tests/test_compose.py`):
```python
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
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_compose.py -v`
Expected: FAIL — `FileNotFoundError` (docker-compose.yml 없음)

- [ ] **Step 3: compose 작성**

**수정 후** (new file: `docker-compose.yml`):
```yaml
services:
  neo4j:
    image: neo4j:5.26-community
    container_name: dartweave-neo4j
    ports:
      - "7474:7474"
      - "7687:7687"
    environment:
      NEO4J_AUTH: neo4j/dartweave1
      NEO4J_PLUGINS: '["graph-data-science"]'
      NEO4J_dbms_security_procedures_unrestricted: gds.*
      NEO4J_dbms_security_procedures_allowlist: gds.*
      NEO4J_server_memory_heap_max__size: 2G
    volumes:
      - neo4j-data:/data
    healthcheck:
      test: ["CMD-SHELL", "wget -qO- http://localhost:7474 || exit 1"]
      interval: 10s
      timeout: 5s
      retries: 12

  postgres:
    image: postgres:16.6
    container_name: dartweave-postgres
    ports:
      - "5435:5432"
    environment:
      POSTGRES_DB: dartweave
      POSTGRES_USER: dartweave
      POSTGRES_PASSWORD: dartweave
    volumes:
      - pg-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U dartweave"]
      interval: 10s
      timeout: 5s
      retries: 12

volumes:
  neo4j-data:
  pg-data:
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_compose.py -v`
Expected: PASS — 3 passed

- [ ] **Step 5: 사용자에게 기동 명령 전달 (자동 실행 금지)**

사용자에게 다음을 안내하고 **직접 실행하도록 요청**한다:
```bash
cd /home/djchoi/deokjinlog/dartweave && docker compose up -d
# 기동 확인
docker compose ps
# GDS 설치 확인 (Neo4j 기동 후 ~30초)
docker exec dartweave-neo4j cypher-shell -u neo4j -p dartweave1 "RETURN gds.version()"
```
Expected: `gds.version()` 이 버전 문자열 반환. 실패 시 GDS↔Neo4j 호환 매트릭스 재확인 필요 (tech-design D7).

- [ ] **Step 6: 커밋**

```bash
git add docker-compose.yml tests/test_compose.py
git commit -m "feat: Docker 스택 정의 (Neo4j+GDS, Postgres) + 포트 충돌 검증"
```

---

### Task 3: Postgres 스키마 (원장·상태·검수)

**Files:**
- Create: `src/dartweave/db/__init__.py` · `src/dartweave/db/models.py`
- Test: `tests/test_models.py`

**Model**: sonnet

- [ ] **Step 1: 실패하는 테스트 작성**

**수정 후** (new file: `tests/test_models.py`):
```python
from dartweave.db.models import Base


def test_all_tables_defined():
    names = set(Base.metadata.tables)
    assert names == {
        "company",
        "disclosure",
        "extraction_run",
        "precision_sample",
        "precision_table",
        "entity_alias",
        "unresolved_mention",
        "relation_change",
        "contradiction",
    }


def test_company_requires_select_reason_column():
    cols = Base.metadata.tables["company"].columns
    assert "selected" in cols and "select_reason" in cols


def test_disclosure_records_failure_reason():
    cols = Base.metadata.tables["disclosure"].columns
    assert "fetch_status" in cols and "fail_reason" in cols


def test_contradiction_has_verdict_slot():
    cols = Base.metadata.tables["contradiction"].columns
    assert "grade" in cols and "verdict" in cols
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dartweave.db'`

- [ ] **Step 3: 모델 구현**

**수정 후** (new file: `src/dartweave/db/__init__.py`):
```python
from dartweave.db.models import Base

__all__ = ["Base"]
```

**수정 후** (new file: `src/dartweave/db/models.py`):
```python
"""Postgres 원장. 그래프는 Neo4j 가 맡고, 여기는 상태·이력·검수만 담는다."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Company(Base):
    __tablename__ = "company"
    corp_code: Mapped[str] = mapped_column(String(8), primary_key=True)
    corp_name: Mapped[str] = mapped_column(String(200))
    stock_code: Mapped[str | None] = mapped_column(String(6))
    corp_cls: Mapped[str | None] = mapped_column(String(1))
    induty_code: Mapped[str | None] = mapped_column(String(10))
    selected: Mapped[bool] = mapped_column(Boolean, default=False)
    # AC-1: 선정 사유를 컬럼으로 강제 — 수동 보정이 기록 없이 일어나는 걸 막는다
    select_reason: Mapped[str | None] = mapped_column(Text)


class Disclosure(Base):
    __tablename__ = "disclosure"
    rcept_no: Mapped[str] = mapped_column(String(14), primary_key=True)
    corp_code: Mapped[str] = mapped_column(String(8), index=True)
    report_nm: Mapped[str] = mapped_column(String(300))
    rcept_dt: Mapped[str] = mapped_column(String(8))
    fiscal_year: Mapped[str] = mapped_column(String(4), index=True)
    as_of: Mapped[str | None] = mapped_column(String(8))
    fetch_status: Mapped[str] = mapped_column(String(20), default="pending")
    # AC-2: 실패를 침묵으로 넘기지 않는다
    fail_reason: Mapped[str | None] = mapped_column(Text)


class ExtractionRun(Base):
    __tablename__ = "extraction_run"
    run_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    model: Mapped[str] = mapped_column(String(100))
    prompt_version: Mapped[str] = mapped_column(String(50))
    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class PrecisionSample(Base):
    __tablename__ = "precision_sample"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    edge_key: Mapped[str] = mapped_column(String(300), index=True)
    rcept_no: Mapped[str] = mapped_column(String(14))
    snippet: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float)
    verdict: Mapped[str | None] = mapped_column(String(20))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime)


class PrecisionTable(Base):
    __tablename__ = "precision_table"
    conf_bucket: Mapped[str] = mapped_column(String(20), primary_key=True)
    n_sample: Mapped[int] = mapped_column(Integer, default=0)
    n_correct: Mapped[int] = mapped_column(Integer, default=0)
    observed_precision: Mapped[float | None] = mapped_column(Float)


class EntityAlias(Base):
    __tablename__ = "entity_alias"
    surface_form: Mapped[str] = mapped_column(String(300), primary_key=True)
    corp_code: Mapped[str] = mapped_column(String(8), index=True)
    source: Mapped[str] = mapped_column(String(10), default="auto")
    added_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class UnresolvedMention(Base):
    __tablename__ = "unresolved_mention"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    surface_form: Mapped[str] = mapped_column(String(300), index=True)
    rcept_no: Mapped[str] = mapped_column(String(14))
    snippet: Mapped[str | None] = mapped_column(Text)
    occurrences: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(20), default="open")


class RelationChange(Base):
    """결정 5 — 시점차는 버리지 않고 여기 적립한다."""

    __tablename__ = "relation_change"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    edge_key: Mapped[str] = mapped_column(String(300), index=True)
    from_fiscal_year: Mapped[str] = mapped_column(String(4))
    to_fiscal_year: Mapped[str] = mapped_column(String(4))
    from_value: Mapped[str | None] = mapped_column(String(100))
    to_value: Mapped[str | None] = mapped_column(String(100))
    from_rcept_no: Mapped[str] = mapped_column(String(14))
    to_rcept_no: Mapped[str] = mapped_column(String(14))


class Contradiction(Base):
    """결정 6 — 모순 검출 결과의 영구 기록. verdict 는 층2 워크벤치가 채운다."""

    __tablename__ = "contradiction"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    grade: Mapped[str] = mapped_column(String(1), index=True)
    edge_key: Mapped[str] = mapped_column(String(300), index=True)
    detail: Mapped[dict] = mapped_column(JSON)
    detected_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    verdict: Mapped[str | None] = mapped_column(String(20))
    verdict_by: Mapped[str | None] = mapped_column(String(100))
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_models.py -v`
Expected: PASS — 4 passed

- [ ] **Step 5: 커밋**

```bash
git add src/dartweave/db tests/test_models.py
git commit -m "feat: Postgres 원장 스키마 9테이블 (선정사유·실패사유·시점차·모순 기록 강제)"
```

---

### Task 4: DART 상태코드 분기

**Files:**
- Create: `src/dartweave/dart/__init__.py` · `src/dartweave/dart/status.py`
- Test: `tests/test_dart_status.py`

**Model**: haiku

> 이 태스크가 슬라이스 1에서 가장 중요한 순수 함수다. `013`(데이터 없음)을 실패로 처리하면 정상 기업이 수집 실패로 기록되어 원장이 오염된다.

- [ ] **Step 1: 실패하는 테스트 작성**

**수정 후** (new file: `tests/test_dart_status.py`):
```python
import pytest

from dartweave.dart.status import Action, DartApiError, classify


def test_000_is_ok():
    assert classify("000") is Action.OK


def test_013_is_empty_not_failure():
    """데이터 없음은 정상. 실패로 처리하면 원장이 오염된다."""
    assert classify("013") is Action.EMPTY


def test_020_is_retryable():
    assert classify("020") is Action.RETRY


def test_010_aborts_immediately():
    """잘못된 키는 재시도해도 소용없다. 즉시 중단."""
    assert classify("010") is Action.ABORT


@pytest.mark.parametrize("code", ["011", "012", "100", "800", "900", "901"])
def test_unknown_codes_are_fatal_not_silently_ok(code):
    assert classify(code) is Action.ABORT


def test_dart_api_error_carries_code():
    err = DartApiError("010", "등록되지 않은 키입니다")
    assert err.status == "010"
    assert "010" in str(err)
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_dart_status.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dartweave.dart'`

- [ ] **Step 3: 구현**

**수정 후** (new file: `src/dartweave/dart/__init__.py`):
```python
__all__ = ["status"]
```

**수정 후** (new file: `src/dartweave/dart/status.py`):
```python
"""DART OpenAPI 상태코드 분기. 모든 응답이 이 한 지점을 통과한다."""
from __future__ import annotations

from enum import Enum


class Action(Enum):
    OK = "ok"
    EMPTY = "empty"
    RETRY = "retry"
    ABORT = "abort"


class DartApiError(RuntimeError):
    def __init__(self, status: str, message: str) -> None:
        self.status = status
        self.message = message
        super().__init__(f"[{status}] {message}")


_MAP = {
    "000": Action.OK,
    "013": Action.EMPTY,
    "020": Action.RETRY,
}


def classify(status: str) -> Action:
    """알 수 없는 코드는 조용히 넘기지 않고 ABORT 한다."""
    return _MAP.get(status, Action.ABORT)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_dart_status.py -v`
Expected: PASS — 11 passed

- [ ] **Step 5: 커밋**

```bash
git add src/dartweave/dart tests/test_dart_status.py
git commit -m "feat: DART 상태코드 분기 (013=정상 빈결과, 010=즉시중단, 미지코드=중단)"
```

---

### Task 5: DART 클라이언트 (레이트리밋 · 재시도)

**Files:**
- Create: `src/dartweave/dart/client.py`
- Test: `tests/test_dart_client.py`

**Model**: sonnet

- [ ] **Step 1: 실패하는 테스트 작성**

**수정 후** (new file: `tests/test_dart_client.py`):
```python
import httpx
import pytest

from dartweave.dart.client import DartClient
from dartweave.dart.status import DartApiError


def _client(handler, **kw) -> DartClient:
    transport = httpx.MockTransport(handler)
    return DartClient(api_key="k" * 40, transport=transport, sleep=lambda _: None, **kw)


def test_get_json_returns_payload_on_000():
    def handler(request):
        return httpx.Response(200, json={"status": "000", "list": [{"a": 1}]})

    assert _client(handler).get_json("list.json", {})["list"] == [{"a": 1}]


def test_empty_status_returns_empty_list_not_error():
    def handler(request):
        return httpx.Response(200, json={"status": "013", "message": "no data"})

    payload = _client(handler).get_json("list.json", {})
    assert payload["status"] == "013"
    assert payload["list"] == []
    assert payload["message"] == "no data", "원본 메시지는 로그용으로 보존한다"


def test_retries_on_020_then_succeeds():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(200, json={"status": "020", "message": "limit"})
        return httpx.Response(200, json={"status": "000", "list": []})

    assert _client(handler, max_retries=5).get_json("list.json", {})["status"] == "000"
    assert calls["n"] == 3


def test_aborts_immediately_on_010_without_retry():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(200, json={"status": "010", "message": "bad key"})

    with pytest.raises(DartApiError) as ei:
        _client(handler, max_retries=5).get_json("list.json", {})
    assert ei.value.status == "010"
    assert calls["n"] == 1, "잘못된 키는 재시도하면 안 됨"


def test_api_key_is_injected_into_every_request():
    seen = {}

    def handler(request):
        seen.update(dict(request.url.params))
        return httpx.Response(200, json={"status": "000"})

    _client(handler).get_json("list.json", {"corp_code": "00126380"})
    assert seen["crtfc_key"] == "k" * 40
    assert seen["corp_code"] == "00126380"
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_dart_client.py -v`
Expected: FAIL — `ImportError: cannot import name 'DartClient'`

- [ ] **Step 3: 구현**

**수정 후** (new file: `src/dartweave/dart/client.py`):
```python
"""DART OpenAPI 클라이언트. 상태코드 분기는 status.classify 한 지점에서만 한다."""
from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import httpx

from dartweave.config import DART_BASE_URL
from dartweave.dart.status import Action, DartApiError, classify


class DartClient:
    def __init__(
        self,
        api_key: str,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        max_retries: int = 3,
        backoff_base: float = 2.0,
        min_interval: float = 0.0,
    ) -> None:
        self._key = api_key
        self._sleep = sleep
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._min_interval = min_interval
        self._last_call = 0.0
        self._http = httpx.Client(
            base_url=DART_BASE_URL, transport=transport, timeout=30.0
        )

    def _throttle(self) -> None:
        if self._min_interval <= 0:
            return
        gap = time.monotonic() - self._last_call
        if gap < self._min_interval:
            self._sleep(self._min_interval - gap)
        self._last_call = time.monotonic()

    def get_json(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        merged = {**params, "crtfc_key": self._key}
        for attempt in range(self._max_retries + 1):
            self._throttle()
            resp = self._http.get(path, params=merged)
            resp.raise_for_status()
            payload = resp.json()
            action = classify(str(payload.get("status", "")))

            if action is Action.OK:
                return payload
            if action is Action.EMPTY:
                # 데이터 없음은 정상. 호출부가 분기하지 않도록 빈 list 를 채워 반환한다.
                return {**payload, "list": []}
            if action is Action.ABORT:
                raise DartApiError(
                    str(payload.get("status")), str(payload.get("message", ""))
                )
            if attempt < self._max_retries:
                self._sleep(self._backoff_base**attempt)

        raise DartApiError("020", f"{self._max_retries}회 재시도 후에도 한도 초과")

    def get_bytes(self, path: str, params: dict[str, Any]) -> bytes:
        """ZIP 응답용 (corpCode.xml, document.xml)."""
        self._throttle()
        resp = self._http.get(path, params={**params, "crtfc_key": self._key})
        resp.raise_for_status()
        return resp.content

    def close(self) -> None:
        self._http.close()
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_dart_client.py -v`
Expected: PASS — 5 passed

- [ ] **Step 5: 커밋**

```bash
git add src/dartweave/dart/client.py tests/test_dart_client.py
git commit -m "feat: DART 클라이언트 (백오프 재시도, 010 즉시중단, 013 빈결과 정규화)"
```

---

### Task 6: corpCode.xml 파서 (전체 기업 목록)

**Files:**
- Create: `src/dartweave/dart/corpcode.py` · `tests/fixtures/__init__.py`
- Test: `tests/test_corpcode.py`

**Model**: haiku

- [ ] **Step 1: 실패하는 테스트 작성**

**수정 후** (new file: `tests/test_corpcode.py`):
```python
import io
import zipfile

from dartweave.dart.corpcode import parse_corpcode_zip

XML = """<?xml version="1.0" encoding="UTF-8"?>
<result>
  <list><corp_code>00126380</corp_code><corp_name>삼성전자</corp_name>
    <stock_code>005930</stock_code><modify_date>20260101</modify_date></list>
  <list><corp_code>00164779</corp_code><corp_name>SK하이닉스</corp_name>
    <stock_code>000660</stock_code><modify_date>20260102</modify_date></list>
  <list><corp_code>00999999</corp_code><corp_name>비상장회사</corp_name>
    <stock_code> </stock_code><modify_date>20260103</modify_date></list>
</result>
"""


def _zip_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("CORPCODE.xml", XML.encode("utf-8"))
    return buf.getvalue()


def test_parses_all_entries():
    rows = parse_corpcode_zip(_zip_bytes())
    assert len(rows) == 3
    assert rows[0].corp_code == "00126380"
    assert rows[0].corp_name == "삼성전자"


def test_blank_stock_code_becomes_none():
    rows = parse_corpcode_zip(_zip_bytes())
    assert rows[2].stock_code is None


def test_listed_only_filter():
    rows = parse_corpcode_zip(_zip_bytes(), listed_only=True)
    assert {r.corp_code for r in rows} == {"00126380", "00164779"}
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_corpcode.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dartweave.dart.corpcode'`

- [ ] **Step 3: 구현**

**수정 후** (new file: `src/dartweave/dart/corpcode.py`):
```python
"""corpCode.xml (ZIP) → 기업 목록."""
from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from xml.etree import ElementTree as ET


@dataclass(frozen=True)
class CorpCodeRow:
    corp_code: str
    corp_name: str
    stock_code: str | None
    modify_date: str


def _text(node: ET.Element, tag: str) -> str:
    el = node.find(tag)
    return (el.text or "").strip() if el is not None else ""


def parse_corpcode_zip(raw: bytes, *, listed_only: bool = False) -> list[CorpCodeRow]:
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        name = next(n for n in z.namelist() if n.lower().endswith(".xml"))
        xml = z.read(name).decode("utf-8")

    root = ET.fromstring(xml)
    rows: list[CorpCodeRow] = []
    for node in root.findall("list"):
        stock = _text(node, "stock_code")
        row = CorpCodeRow(
            corp_code=_text(node, "corp_code"),
            corp_name=_text(node, "corp_name"),
            stock_code=stock or None,
            modify_date=_text(node, "modify_date"),
        )
        if listed_only and row.stock_code is None:
            continue
        rows.append(row)
    return rows
```

**수정 후** (new file: `tests/fixtures/__init__.py`):
```python
"""계약 fixture 모음 — 실 API 없이 파이프라인을 구동하기 위한 응답 표본."""
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_corpcode.py -v`
Expected: PASS — 3 passed

- [ ] **Step 5: 커밋**

```bash
git add src/dartweave/dart/corpcode.py tests/test_corpcode.py tests/fixtures
git commit -m "feat: corpCode.xml ZIP 파서 (공백 종목코드 정규화, 상장사 필터)"
```

---

### Task 7: 기업개황 파서 (induty_code 확보)

**Files:**
- Create: `src/dartweave/dart/company.py`
- Test: `tests/test_company_api.py`

**Model**: haiku

- [ ] **Step 1: 실패하는 테스트 작성**

**수정 후** (new file: `tests/test_company_api.py`):
```python
from dartweave.dart.company import parse_company

PAYLOAD = {
    "status": "000",
    "corp_name": "삼성전자(주)",
    "corp_name_eng": "SAMSUNG ELECTRONICS CO,.LTD",
    "stock_name": "삼성전자",
    "stock_code": "005930",
    "corp_cls": "Y",
    "induty_code": "26410",
    "est_dt": "19690113",
    "acc_mt": "12",
}


def test_extracts_industry_and_class():
    c = parse_company("00126380", PAYLOAD)
    assert c.corp_code == "00126380"
    assert c.induty_code == "26410"
    assert c.corp_cls == "Y"


def test_missing_optional_fields_become_none():
    c = parse_company("00999999", {"status": "000", "corp_name": "무명"})
    assert c.induty_code is None
    assert c.stock_code is None
    assert c.corp_name == "무명"


def test_blank_string_is_none_not_empty():
    c = parse_company("00999999", {"status": "000", "corp_name": "x", "induty_code": " "})
    assert c.induty_code is None
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_company_api.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dartweave.dart.company'`

- [ ] **Step 3: 구현**

**수정 후** (new file: `src/dartweave/dart/company.py`):
```python
"""기업개황 API 응답 → 기업 레코드."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CompanyInfo:
    corp_code: str
    corp_name: str
    stock_code: str | None
    corp_cls: str | None
    induty_code: str | None
    est_dt: str | None
    acc_mt: str | None


def _clean(payload: dict[str, Any], key: str) -> str | None:
    value = str(payload.get(key, "")).strip()
    return value or None


def parse_company(corp_code: str, payload: dict[str, Any]) -> CompanyInfo:
    return CompanyInfo(
        corp_code=corp_code,
        corp_name=_clean(payload, "corp_name") or "",
        stock_code=_clean(payload, "stock_code"),
        corp_cls=_clean(payload, "corp_cls"),
        induty_code=_clean(payload, "induty_code"),
        est_dt=_clean(payload, "est_dt"),
        acc_mt=_clean(payload, "acc_mt"),
    )
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_company_api.py -v`
Expected: PASS — 3 passed

- [ ] **Step 5: 커밋**

```bash
git add src/dartweave/dart/company.py tests/test_company_api.py
git commit -m "feat: 기업개황 파서 (induty_code 확보, 공백→None 정규화)"
```

---

### Task 8: 대상 선정 (산업군 필터 + 선정 사유 강제)

**Files:**
- Create: `src/dartweave/select/__init__.py` · `src/dartweave/select/targets.py`
- Test: `tests/test_targets.py`

**Model**: sonnet

- [ ] **Step 1: 실패하는 테스트 작성**

**수정 후** (new file: `tests/test_targets.py`):
```python
import pytest

from dartweave.dart.company import CompanyInfo
from dartweave.select.targets import IndustryFilter, select_targets


def _c(code, name, induty, cls="Y"):
    return CompanyInfo(code, name, "000000", cls, induty, None, None)


COMPANIES = [
    _c("001", "반도체소재", "20119"),
    _c("002", "반도체제조", "26110"),
    _c("003", "제빵회사", "10711"),
    _c("004", "장비회사", "29271"),
    _c("005", "비상장반도체", "26110", cls="N"),
]


def test_selects_by_industry_prefix():
    f = IndustryFilter(prefixes=["261"], manual_add={}, manual_exclude=set())
    picked = select_targets(COMPANIES, f)
    assert {p.corp_code for p in picked} == {"002", "005"}


def test_manual_add_requires_reason():
    with pytest.raises(ValueError, match="사유"):
        IndustryFilter(prefixes=["261"], manual_add={"001": ""}, manual_exclude=set())


def test_manual_add_included_with_reason_recorded():
    f = IndustryFilter(
        prefixes=["261"],
        manual_add={"004": "반도체 장비 — 업종코드가 기계로 분류되어 자동필터 누락"},
        manual_exclude=set(),
    )
    picked = {p.corp_code: p for p in select_targets(COMPANIES, f)}
    assert "004" in picked
    assert "자동필터 누락" in picked["004"].reason


def test_auto_selection_also_records_reason():
    f = IndustryFilter(prefixes=["261"], manual_add={}, manual_exclude=set())
    picked = {p.corp_code: p for p in select_targets(COMPANIES, f)}
    assert picked["002"].reason.startswith("업종코드")


def test_manual_exclude_wins_over_auto():
    f = IndustryFilter(prefixes=["261"], manual_add={}, manual_exclude={"005"})
    assert {p.corp_code for p in select_targets(COMPANIES, f)} == {"002"}
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_targets.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dartweave.select'`

- [ ] **Step 3: 구현**

**수정 후** (new file: `src/dartweave/select/__init__.py`):
```python
__all__ = ["targets"]
```

**수정 후** (new file: `src/dartweave/select/targets.py`):
```python
"""대상 기업 선정.

결정 2 — 시드 N사가 아니라 산업군 전체. 자동 업종코드 필터만으로는
장비·소재 기업이 다른 코드로 흩어져 누락되므로 수동 보정을 허용하되,
**사유 없는 수동 추가를 금지**한다 (AC-1).
"""
from __future__ import annotations

from dataclasses import dataclass

from dartweave.dart.company import CompanyInfo


@dataclass(frozen=True)
class SelectedCompany:
    corp_code: str
    corp_name: str
    induty_code: str | None
    reason: str


class IndustryFilter:
    def __init__(
        self,
        *,
        prefixes: list[str],
        manual_add: dict[str, str],
        manual_exclude: set[str],
    ) -> None:
        for corp_code, reason in manual_add.items():
            if not reason.strip():
                raise ValueError(f"{corp_code}: 수동 추가에는 사유가 필요합니다")
        self.prefixes = prefixes
        self.manual_add = manual_add
        self.manual_exclude = manual_exclude

    def auto_match(self, induty_code: str | None) -> bool:
        if not induty_code:
            return False
        return any(induty_code.startswith(p) for p in self.prefixes)


def select_targets(
    companies: list[CompanyInfo], flt: IndustryFilter
) -> list[SelectedCompany]:
    picked: list[SelectedCompany] = []
    for c in companies:
        if c.corp_code in flt.manual_exclude:
            continue
        if c.corp_code in flt.manual_add:
            reason = f"수동 추가 — {flt.manual_add[c.corp_code]}"
        elif flt.auto_match(c.induty_code):
            reason = f"업종코드 {c.induty_code} 가 대상 접두사 {flt.prefixes} 에 부합"
        else:
            continue
        picked.append(
            SelectedCompany(c.corp_code, c.corp_name, c.induty_code, reason)
        )
    return picked
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_targets.py -v`
Expected: PASS — 5 passed

- [ ] **Step 5: 커밋**

```bash
git add src/dartweave/select tests/test_targets.py
git commit -m "feat: 산업군 대상 선정 (사유 없는 수동 추가 금지, 자동선정도 사유 기록)"
```

---

### Task 9: 공시목록 수집 → 원장 기록

**Files:**
- Create: `src/dartweave/dart/disclosure.py`
- Test: `tests/test_disclosure.py`

**Model**: sonnet

- [ ] **Step 1: 실패하는 테스트 작성**

**수정 후** (new file: `tests/test_disclosure.py`):
```python
from dartweave.dart.disclosure import fiscal_year_of, parse_disclosure_list

PAYLOAD = {
    "status": "000",
    "list": [
        {
            "corp_code": "00126380",
            "report_nm": "사업보고서 (2025.12)",
            "rcept_no": "20260311000123",
            "rcept_dt": "20260311",
        },
        {
            "corp_code": "00126380",
            "report_nm": "분기보고서 (2025.09)",
            "rcept_no": "20251114000456",
            "rcept_dt": "20251114",
        },
    ],
}


def test_fiscal_year_comes_from_rcept_no_prefix():
    assert fiscal_year_of("20260311000123") == "2026"


def test_parses_rows():
    rows = parse_disclosure_list(PAYLOAD)
    assert len(rows) == 2
    assert rows[0].rcept_no == "20260311000123"
    assert rows[0].fiscal_year == "2026"


def test_empty_status_yields_no_rows_and_no_error():
    assert parse_disclosure_list({"status": "013", "list": []}) == []


def test_report_name_filter():
    rows = parse_disclosure_list(PAYLOAD, name_contains="사업보고서")
    assert [r.rcept_no for r in rows] == ["20260311000123"]
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_disclosure.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dartweave.dart.disclosure'`

- [ ] **Step 3: 구현**

**수정 후** (new file: `src/dartweave/dart/disclosure.py`):
```python
"""공시목록 → 원장 레코드."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DisclosureRow:
    rcept_no: str
    corp_code: str
    report_nm: str
    rcept_dt: str
    fiscal_year: str


def fiscal_year_of(rcept_no: str) -> str:
    """결정 5 — 접수번호 앞 4자리가 시점 스코프의 1차 키."""
    return rcept_no[:4]


def parse_disclosure_list(
    payload: dict[str, Any], *, name_contains: str | None = None
) -> list[DisclosureRow]:
    rows: list[DisclosureRow] = []
    for item in payload.get("list", []):
        report_nm = str(item.get("report_nm", "")).strip()
        if name_contains and name_contains not in report_nm:
            continue
        rcept_no = str(item.get("rcept_no", "")).strip()
        rows.append(
            DisclosureRow(
                rcept_no=rcept_no,
                corp_code=str(item.get("corp_code", "")).strip(),
                report_nm=report_nm,
                rcept_dt=str(item.get("rcept_dt", "")).strip(),
                fiscal_year=fiscal_year_of(rcept_no),
            )
        )
    return rows
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_disclosure.py -v`
Expected: PASS — 4 passed

- [ ] **Step 5: 커밋**

```bash
git add src/dartweave/dart/disclosure.py tests/test_disclosure.py
git commit -m "feat: 공시목록 파서 + 접수번호 기반 사업연도 도출"
```

---

### Task 10: 정형 관계 파서 — 최대주주 현황

**Files:**
- Create: `src/dartweave/parse/__init__.py` · `src/dartweave/parse/relation.py` · `src/dartweave/parse/structured_rel.py`
- Test: `tests/test_structured_rel.py`

**Model**: sonnet

- [ ] **Step 1: 실패하는 테스트 작성**

**수정 후** (new file: `tests/test_structured_rel.py`):
```python
from dartweave.parse.relation import EdgeType, Source
from dartweave.parse.structured_rel import parse_major_shareholder

PAYLOAD = {
    "status": "000",
    "list": [
        {
            "corp_code": "00126380",
            "nm": "삼성생명보험",
            "relate": "최대주주",
            "trmend_posesn_stock_qota_rt": "8.51",
            "rcept_no": "20260311000123",
            "stlm_dt": "2025-12-31",
        },
        {
            "corp_code": "00126380",
            "nm": "삼성물산",
            "relate": "특수관계인",
            "trmend_posesn_stock_qota_rt": "5.01",
            "rcept_no": "20260311000123",
            "stlm_dt": "2025-12-31",
        },
    ],
}


def test_builds_shareholder_edges():
    edges = parse_major_shareholder(PAYLOAD)
    assert len(edges) == 2
    e = edges[0]
    assert e.edge_type is EdgeType.MAJOR_SHAREHOLDER_OF
    assert e.source_name == "삼성생명보험"
    assert e.target_corp_code == "00126380"
    assert e.share_pct == 8.51


def test_carries_provenance_and_scope():
    e = parse_major_shareholder(PAYLOAD)[0]
    assert e.rcept_no == "20260311000123"
    assert e.fiscal_year == "2026"
    assert e.as_of == "20251231"
    assert e.source is Source.STRUCTURED
    assert e.confidence is None


def test_unparsable_ratio_becomes_none_not_zero():
    payload = {
        "status": "000",
        "list": [
            {
                "corp_code": "00126380",
                "nm": "미상",
                "trmend_posesn_stock_qota_rt": "-",
                "rcept_no": "20260311000123",
                "stlm_dt": "2025-12-31",
            }
        ],
    }
    assert parse_major_shareholder(payload)[0].share_pct is None


def test_comma_separated_ratio_is_parsed():
    payload = {
        "status": "000",
        "list": [
            {
                "corp_code": "00126380",
                "nm": "x",
                "trmend_posesn_stock_qota_rt": "1,234.5",
                "rcept_no": "20260311000123",
                "stlm_dt": "2025-12-31",
            }
        ],
    }
    assert parse_major_shareholder(payload)[0].share_pct == 1234.5
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_structured_rel.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dartweave.parse'`

- [ ] **Step 3: 구현**

**수정 후** (new file: `src/dartweave/parse/__init__.py`):
```python
__all__ = ["relation", "structured_rel"]
```

**수정 후** (new file: `src/dartweave/parse/relation.py`):
```python
"""관계 레코드 — 정형/본문 양쪽이 같은 형태로 수렴한다."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class EdgeType(Enum):
    MAJOR_SHAREHOLDER_OF = "MAJOR_SHAREHOLDER_OF"
    INVESTS_IN = "INVESTS_IN"
    HOLDS_5PCT = "HOLDS_5PCT"
    EXECUTIVE_OF = "EXECUTIVE_OF"
    AUDITED_BY = "AUDITED_BY"
    SUPPLIES_TO = "SUPPLIES_TO"
    PRODUCES = "PRODUCES"


class Source(Enum):
    STRUCTURED = "structured"
    TEXT = "text"


@dataclass(frozen=True)
class RelationEdge:
    edge_type: EdgeType
    source_name: str
    source_corp_code: str | None
    target_name: str | None
    target_corp_code: str | None
    rcept_no: str
    fiscal_year: str
    as_of: str | None
    source: Source
    share_pct: float | None = None
    confidence: float | None = None
    reporter_corp_code: str | None = None

    @property
    def edge_key(self) -> str:
        """엣지 정체성. mention_count 집계·모순 기록의 키."""
        src = self.source_corp_code or self.source_name
        tgt = self.target_corp_code or self.target_name or ""
        return f"{src}|{self.edge_type.value}|{tgt}"
```

**수정 후** (new file: `src/dartweave/parse/structured_rel.py`):
```python
"""정형 API 응답 → 관계 엣지. 이 경로의 엣지는 confidence 를 갖지 않는다."""
from __future__ import annotations

from typing import Any

from dartweave.parse.relation import EdgeType, RelationEdge, Source


def parse_ratio(raw: Any) -> float | None:
    """'-', '', '1,234.5' 같은 실제 응답 변형을 흡수한다. 실패는 0이 아니라 None."""
    text = str(raw or "").strip().replace(",", "")
    if not text or text == "-":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def normalize_as_of(raw: Any) -> str | None:
    text = str(raw or "").strip().replace("-", "").replace(".", "")
    return text if len(text) == 8 and text.isdigit() else None


def parse_major_shareholder(payload: dict[str, Any]) -> list[RelationEdge]:
    edges: list[RelationEdge] = []
    for item in payload.get("list", []):
        rcept_no = str(item.get("rcept_no", "")).strip()
        target = str(item.get("corp_code", "")).strip()
        edges.append(
            RelationEdge(
                edge_type=EdgeType.MAJOR_SHAREHOLDER_OF,
                source_name=str(item.get("nm", "")).strip(),
                source_corp_code=None,
                target_name=None,
                target_corp_code=target,
                rcept_no=rcept_no,
                fiscal_year=rcept_no[:4],
                as_of=normalize_as_of(item.get("stlm_dt")),
                source=Source.STRUCTURED,
                share_pct=parse_ratio(item.get("trmend_posesn_stock_qota_rt")),
                reporter_corp_code=target,
            )
        )
    return edges
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_structured_rel.py -v`
Expected: PASS — 4 passed

- [ ] **Step 5: 커밋**

```bash
git add src/dartweave/parse tests/test_structured_rel.py
git commit -m "feat: 최대주주 현황 → 지분 엣지 (비율 파싱 실패는 0 아닌 None)"
```

---

### Task 11: 정형 관계 파서 — 타법인 출자 · 대량보유

**Files:**
- Modify: `src/dartweave/parse/structured_rel.py`
- Test: `tests/test_structured_rel_more.py`

**Model**: sonnet

- [ ] **Step 1: 실패하는 테스트 작성**

**수정 후** (new file: `tests/test_structured_rel_more.py`):
```python
from dartweave.parse.relation import EdgeType
from dartweave.parse.structured_rel import parse_investment, parse_major_holding

INVEST = {
    "status": "000",
    "list": [
        {
            "corp_code": "00126380",
            "inv_prm": "삼성디스플레이",
            "trmend_qota_rt": "84.8",
            "rcept_no": "20260311000123",
            "stlm_dt": "2025-12-31",
        }
    ],
}

HOLDING = {
    "status": "000",
    "list": [
        {
            "corp_code": "00164779",
            "repror": "국민연금공단",
            "stkqy_irds_rt": "7.12",
            "rcept_no": "20260201000777",
            "stlm_dt": "2026-01-31",
        }
    ],
}


def test_investment_edge_direction_is_holder_to_investee():
    e = parse_investment(INVEST)[0]
    assert e.edge_type is EdgeType.INVESTS_IN
    assert e.source_corp_code == "00126380"
    assert e.target_name == "삼성디스플레이"
    assert e.share_pct == 84.8


def test_major_holding_edge():
    e = parse_major_holding(HOLDING)[0]
    assert e.edge_type is EdgeType.HOLDS_5PCT
    assert e.source_name == "국민연금공단"
    assert e.target_corp_code == "00164779"
    assert e.share_pct == 7.12


def test_reporter_is_recorded_for_cross_check():
    """교차확인은 '누가 신고했나'를 알아야 성립한다."""
    assert parse_investment(INVEST)[0].reporter_corp_code == "00126380"
    assert parse_major_holding(HOLDING)[0].reporter_corp_code == "00164779"
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_structured_rel_more.py -v`
Expected: FAIL — `ImportError: cannot import name 'parse_investment'`

- [ ] **Step 3: 파서 추가**

**원본** (`src/dartweave/parse/structured_rel.py:41-60`):
```python
def parse_major_shareholder(payload: dict[str, Any]) -> list[RelationEdge]:
    edges: list[RelationEdge] = []
    for item in payload.get("list", []):
        rcept_no = str(item.get("rcept_no", "")).strip()
        target = str(item.get("corp_code", "")).strip()
        edges.append(
            RelationEdge(
                edge_type=EdgeType.MAJOR_SHAREHOLDER_OF,
                source_name=str(item.get("nm", "")).strip(),
                source_corp_code=None,
                target_name=None,
                target_corp_code=target,
                rcept_no=rcept_no,
                fiscal_year=rcept_no[:4],
                as_of=normalize_as_of(item.get("stlm_dt")),
                source=Source.STRUCTURED,
                share_pct=parse_ratio(item.get("trmend_posesn_stock_qota_rt")),
                reporter_corp_code=target,
            )
        )
    return edges
```

**수정 후**:
```python
def parse_major_shareholder(payload: dict[str, Any]) -> list[RelationEdge]:
    edges: list[RelationEdge] = []
    for item in payload.get("list", []):
        rcept_no = str(item.get("rcept_no", "")).strip()
        target = str(item.get("corp_code", "")).strip()
        edges.append(
            RelationEdge(
                edge_type=EdgeType.MAJOR_SHAREHOLDER_OF,
                source_name=str(item.get("nm", "")).strip(),
                source_corp_code=None,
                target_name=None,
                target_corp_code=target,
                rcept_no=rcept_no,
                fiscal_year=rcept_no[:4],
                as_of=normalize_as_of(item.get("stlm_dt")),
                source=Source.STRUCTURED,
                share_pct=parse_ratio(item.get("trmend_posesn_stock_qota_rt")),
                reporter_corp_code=target,
            )
        )
    return edges


def parse_investment(payload: dict[str, Any]) -> list[RelationEdge]:
    """타법인 출자현황 — 신고 주체가 보유자다 (최대주주 현황과 방향이 반대)."""
    edges: list[RelationEdge] = []
    for item in payload.get("list", []):
        rcept_no = str(item.get("rcept_no", "")).strip()
        holder = str(item.get("corp_code", "")).strip()
        edges.append(
            RelationEdge(
                edge_type=EdgeType.INVESTS_IN,
                source_name="",
                source_corp_code=holder,
                target_name=str(item.get("inv_prm", "")).strip(),
                target_corp_code=None,
                rcept_no=rcept_no,
                fiscal_year=rcept_no[:4],
                as_of=normalize_as_of(item.get("stlm_dt")),
                source=Source.STRUCTURED,
                share_pct=parse_ratio(item.get("trmend_qota_rt")),
                reporter_corp_code=holder,
            )
        )
    return edges


def parse_major_holding(payload: dict[str, Any]) -> list[RelationEdge]:
    """지분공시(5% 룰) — 최대주주 현황과 맞대볼 상대."""
    edges: list[RelationEdge] = []
    for item in payload.get("list", []):
        rcept_no = str(item.get("rcept_no", "")).strip()
        target = str(item.get("corp_code", "")).strip()
        edges.append(
            RelationEdge(
                edge_type=EdgeType.HOLDS_5PCT,
                source_name=str(item.get("repror", "")).strip(),
                source_corp_code=None,
                target_name=None,
                target_corp_code=target,
                rcept_no=rcept_no,
                fiscal_year=rcept_no[:4],
                as_of=normalize_as_of(item.get("stlm_dt")),
                source=Source.STRUCTURED,
                share_pct=parse_ratio(item.get("stkqy_irds_rt")),
                reporter_corp_code=target,
            )
        )
    return edges
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_structured_rel_more.py tests/test_structured_rel.py -v`
Expected: PASS — 7 passed

- [ ] **Step 5: 커밋**

```bash
git add src/dartweave/parse/structured_rel.py tests/test_structured_rel_more.py
git commit -m "feat: 타법인 출자·대량보유 파서 (신고 주체 기록으로 교차확인 준비)"
```

---

### Task 12: 정형 관계 파서 — 임원 · 감사인

**Files:**
- Modify: `src/dartweave/parse/structured_rel.py`
- Test: `tests/test_structured_rel_people.py`

**Model**: sonnet

- [ ] **Step 1: 실패하는 테스트 작성**

**수정 후** (new file: `tests/test_structured_rel_people.py`):
```python
from dartweave.parse.relation import EdgeType
from dartweave.parse.structured_rel import parse_auditor, parse_executives

EXEC = {
    "status": "000",
    "list": [
        {
            "corp_code": "00126380",
            "nm": "홍길동",
            "ofcps": "대표이사",
            "rcept_no": "20260311000123",
            "stlm_dt": "2025-12-31",
        },
        {
            "corp_code": "00126380",
            "nm": "",
            "ofcps": "사외이사",
            "rcept_no": "20260311000123",
            "stlm_dt": "2025-12-31",
        },
    ],
}

AUDITOR = {
    "status": "000",
    "list": [
        {
            "corp_code": "00126380",
            "adtor": "삼일회계법인",
            "adt_opinion": "적정",
            "rcept_no": "20260311000123",
            "stlm_dt": "2025-12-31",
        }
    ],
}


def test_executive_edges_skip_blank_names():
    edges = parse_executives(EXEC)
    assert len(edges) == 1
    assert edges[0].edge_type is EdgeType.EXECUTIVE_OF
    assert edges[0].source_name == "홍길동"


def test_auditor_edge_direction_is_company_to_auditor():
    e = parse_auditor(AUDITOR)[0]
    assert e.edge_type is EdgeType.AUDITED_BY
    assert e.source_corp_code == "00126380"
    assert e.target_name == "삼일회계법인"


def test_people_and_auditor_edges_have_no_share_pct():
    assert parse_executives(EXEC)[0].share_pct is None
    assert parse_auditor(AUDITOR)[0].share_pct is None
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_structured_rel_people.py -v`
Expected: FAIL — `ImportError: cannot import name 'parse_executives'`

- [ ] **Step 3: 파서 추가 (파일 끝에 append)**

**원본** (`src/dartweave/parse/structured_rel.py:113-134`):
```python
def parse_major_holding(payload: dict[str, Any]) -> list[RelationEdge]:
    """지분공시(5% 룰) — 최대주주 현황과 맞대볼 상대."""
    edges: list[RelationEdge] = []
    for item in payload.get("list", []):
        rcept_no = str(item.get("rcept_no", "")).strip()
        target = str(item.get("corp_code", "")).strip()
        edges.append(
            RelationEdge(
                edge_type=EdgeType.HOLDS_5PCT,
                source_name=str(item.get("repror", "")).strip(),
                source_corp_code=None,
                target_name=None,
                target_corp_code=target,
                rcept_no=rcept_no,
                fiscal_year=rcept_no[:4],
                as_of=normalize_as_of(item.get("stlm_dt")),
                source=Source.STRUCTURED,
                share_pct=parse_ratio(item.get("stkqy_irds_rt")),
                reporter_corp_code=target,
            )
        )
    return edges
```

**수정 후**:
```python
def parse_major_holding(payload: dict[str, Any]) -> list[RelationEdge]:
    """지분공시(5% 룰) — 최대주주 현황과 맞대볼 상대."""
    edges: list[RelationEdge] = []
    for item in payload.get("list", []):
        rcept_no = str(item.get("rcept_no", "")).strip()
        target = str(item.get("corp_code", "")).strip()
        edges.append(
            RelationEdge(
                edge_type=EdgeType.HOLDS_5PCT,
                source_name=str(item.get("repror", "")).strip(),
                source_corp_code=None,
                target_name=None,
                target_corp_code=target,
                rcept_no=rcept_no,
                fiscal_year=rcept_no[:4],
                as_of=normalize_as_of(item.get("stlm_dt")),
                source=Source.STRUCTURED,
                share_pct=parse_ratio(item.get("stkqy_irds_rt")),
                reporter_corp_code=target,
            )
        )
    return edges


def parse_executives(payload: dict[str, Any]) -> list[RelationEdge]:
    """임원 현황 — 동일인이 여러 회사에 걸리면 그게 겸직 네트워크가 된다."""
    edges: list[RelationEdge] = []
    for item in payload.get("list", []):
        name = str(item.get("nm", "")).strip()
        if not name:
            continue
        rcept_no = str(item.get("rcept_no", "")).strip()
        target = str(item.get("corp_code", "")).strip()
        edges.append(
            RelationEdge(
                edge_type=EdgeType.EXECUTIVE_OF,
                source_name=name,
                source_corp_code=None,
                target_name=None,
                target_corp_code=target,
                rcept_no=rcept_no,
                fiscal_year=rcept_no[:4],
                as_of=normalize_as_of(item.get("stlm_dt")),
                source=Source.STRUCTURED,
                reporter_corp_code=target,
            )
        )
    return edges


def parse_auditor(payload: dict[str, Any]) -> list[RelationEdge]:
    """회계감사인 — 대조 상대가 없어 T2 로 남는다."""
    edges: list[RelationEdge] = []
    for item in payload.get("list", []):
        auditor = str(item.get("adtor", "")).strip()
        if not auditor:
            continue
        rcept_no = str(item.get("rcept_no", "")).strip()
        company = str(item.get("corp_code", "")).strip()
        edges.append(
            RelationEdge(
                edge_type=EdgeType.AUDITED_BY,
                source_name="",
                source_corp_code=company,
                target_name=auditor,
                target_corp_code=None,
                rcept_no=rcept_no,
                fiscal_year=rcept_no[:4],
                as_of=normalize_as_of(item.get("stlm_dt")),
                source=Source.STRUCTURED,
                reporter_corp_code=company,
            )
        )
    return edges
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/ -k structured_rel -v`
Expected: PASS — 10 passed

- [ ] **Step 5: 커밋**

```bash
git add src/dartweave/parse/structured_rel.py tests/test_structured_rel_people.py
git commit -m "feat: 임원·감사인 파서 (빈 이름 스킵, 겸직 네트워크 재료 확보)"
```

---

### Task 13: 시점 스코프 판정 (시점차 ≠ 불일치)

**Files:**
- Create: `src/dartweave/trust/__init__.py` · `src/dartweave/trust/scope.py`
- Test: `tests/test_scope.py`

**Model**: sonnet

> 결정 5. 이걸 안 넣으면 정상적인 지분 매각이 전부 "모순"으로 튀어나와 1급의 권위가 무너진다.

- [ ] **Step 1: 실패하는 테스트 작성**

**수정 후** (new file: `tests/test_scope.py`):
```python
from dartweave.parse.relation import EdgeType, RelationEdge, Source
from dartweave.trust.scope import Verdict, compare_scope


def _edge(rcept_no, as_of, pct):
    return RelationEdge(
        edge_type=EdgeType.MAJOR_SHAREHOLDER_OF,
        source_name="A",
        source_corp_code=None,
        target_name=None,
        target_corp_code="B",
        rcept_no=rcept_no,
        fiscal_year=rcept_no[:4],
        as_of=as_of,
        source=Source.STRUCTURED,
        share_pct=pct,
    )


def test_different_fiscal_year_is_change_not_mismatch():
    a = _edge("20240311000001", "20231231", 30.0)
    b = _edge("20250311000001", "20241231", 25.0)
    assert compare_scope(a, b) is Verdict.CHANGE


def test_same_scope_different_value_is_mismatch():
    a = _edge("20250311000001", "20241231", 30.0)
    b = _edge("20250315000009", "20241231", 25.0)
    assert compare_scope(a, b) is Verdict.MISMATCH


def test_same_scope_same_value_is_agreement():
    a = _edge("20250311000001", "20241231", 30.0)
    b = _edge("20250315000009", "20241231", 30.0)
    assert compare_scope(a, b) is Verdict.AGREE


def test_small_rounding_difference_is_agreement():
    a = _edge("20250311000001", "20241231", 30.00)
    b = _edge("20250315000009", "20241231", 30.004)
    assert compare_scope(a, b) is Verdict.AGREE


def test_same_fiscal_year_but_different_as_of_is_change():
    """같은 연도라도 기준일이 다르면 변동이다."""
    a = _edge("20250311000001", "20241231", 30.0)
    b = _edge("20250901000009", "20250630", 25.0)
    assert compare_scope(a, b) is Verdict.CHANGE


def test_missing_as_of_falls_back_to_fiscal_year():
    a = _edge("20250311000001", None, 30.0)
    b = _edge("20250315000009", None, 25.0)
    assert compare_scope(a, b) is Verdict.MISMATCH
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_scope.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dartweave.trust'`

- [ ] **Step 3: 구현**

**수정 후** (new file: `src/dartweave/trust/__init__.py`):
```python
__all__ = ["scope"]
```

**수정 후** (new file: `src/dartweave/trust/scope.py`):
```python
"""시점 스코프 판정.

결정 5 — 2023년 30% / 2024년 25% 는 불일치가 아니라 지분 매각이다.
정상 변화를 오류로 띄우면 1급 모순의 권위가 통째로 무너진다.
"""
from __future__ import annotations

from enum import Enum

from dartweave.parse.relation import RelationEdge

RATIO_TOLERANCE = 0.01  # 반올림 표기 차이 흡수


class Verdict(Enum):
    AGREE = "agree"
    MISMATCH = "mismatch"
    CHANGE = "change"


def scope_key(edge: RelationEdge) -> tuple[str, str]:
    """기준일이 있으면 그게 우선. 없으면 사업연도로 폴백."""
    return (edge.fiscal_year, edge.as_of or edge.fiscal_year)


def compare_scope(a: RelationEdge, b: RelationEdge) -> Verdict:
    if scope_key(a) != scope_key(b):
        return Verdict.CHANGE
    if a.share_pct is None or b.share_pct is None:
        return Verdict.AGREE if a.share_pct == b.share_pct else Verdict.MISMATCH
    if abs(a.share_pct - b.share_pct) <= RATIO_TOLERANCE:
        return Verdict.AGREE
    return Verdict.MISMATCH
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_scope.py -v`
Expected: PASS — 6 passed

- [ ] **Step 5: 커밋**

```bash
git add src/dartweave/trust tests/test_scope.py
git commit -m "feat: 시점 스코프 판정 (시점차는 CHANGE, 같은 스코프만 MISMATCH)"
```

---

### Task 14: mention_count 집계 (출처 주체 기준)

**Files:**
- Create: `src/dartweave/trust/mention.py`
- Test: `tests/test_mention.py`

**Model**: sonnet

> 요구사항 결정 3의 핵심. **연차 반복이 2 이상으로 세어지면 AC-3 실패다.**

- [ ] **Step 1: 실패하는 테스트 작성**

**수정 후** (new file: `tests/test_mention.py`):
```python
from dartweave.parse.relation import EdgeType, RelationEdge, Source
from dartweave.trust.mention import count_mentions

def _edge(reporter, rcept_no, report_kind):
    return RelationEdge(
        edge_type=EdgeType.MAJOR_SHAREHOLDER_OF,
        source_name="A",
        source_corp_code="001",
        target_name=None,
        target_corp_code="002",
        rcept_no=rcept_no,
        fiscal_year=rcept_no[:4],
        as_of=None,
        source=Source.STRUCTURED,
        reporter_corp_code=reporter,
    ), report_kind


def test_same_company_across_three_years_counts_as_one():
    """AC-3 — 같은 회사의 연차 반복은 근거가 세 겹이 된 게 아니라 복사다."""
    pairs = [
        _edge("001", "20240311000001", "사업보고서"),
        _edge("001", "20250311000001", "사업보고서"),
        _edge("001", "20260311000001", "사업보고서"),
    ]
    counts = count_mentions(pairs)
    assert counts["001|MAJOR_SHAREHOLDER_OF|002"] == 1


def test_two_different_companies_count_as_two():
    pairs = [
        _edge("001", "20250311000001", "사업보고서"),
        _edge("002", "20250311000009", "사업보고서"),
    ]
    assert count_mentions(pairs)["001|MAJOR_SHAREHOLDER_OF|002"] == 2


def test_different_report_kinds_count_separately():
    pairs = [
        _edge("001", "20250311000001", "사업보고서"),
        _edge("001", "20250401000002", "주요사항보고서"),
    ]
    assert count_mentions(pairs)["001|MAJOR_SHAREHOLDER_OF|002"] == 2


def test_mixed_case_company_dominates_over_year_repetition():
    pairs = [
        _edge("001", "20240311000001", "사업보고서"),
        _edge("001", "20250311000001", "사업보고서"),
        _edge("002", "20250311000009", "사업보고서"),
    ]
    assert count_mentions(pairs)["001|MAJOR_SHAREHOLDER_OF|002"] == 2
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_mention.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dartweave.trust.mention'`

- [ ] **Step 3: 구현**

**수정 후** (new file: `src/dartweave/trust/mention.py`):
```python
"""mention_count 집계.

요구사항 결정 3 — 집계 키는 (엣지 정체성, **출처 주체**) 다.
출처 주체 = (보고 회사, 보고서 종류). 같은 회사의 연차 반복은 1로 친다.
이 규칙을 어기면 자기 인용으로 가중치가 부풀려진다.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from dartweave.parse.relation import RelationEdge


def count_mentions(
    pairs: Iterable[tuple[RelationEdge, str]],
) -> dict[str, int]:
    """pairs: (엣지, 보고서 종류) 목록 → {edge_key: 서로 다른 출처 주체 수}"""
    subjects: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for edge, report_kind in pairs:
        subject = (edge.reporter_corp_code or "", report_kind)
        subjects[edge.edge_key].add(subject)
    return {key: len(s) for key, s in subjects.items()}
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_mention.py -v`
Expected: PASS — 4 passed

- [ ] **Step 5: 커밋**

```bash
git add src/dartweave/trust/mention.py tests/test_mention.py
git commit -m "feat: mention_count 를 출처 주체 기준으로 집계 (연차 반복 자기인용 차단)"
```

---

### Task 15: 교차확인 (정형 ↔ 정형)

**Files:**
- Create: `src/dartweave/trust/crosscheck.py`
- Test: `tests/test_crosscheck.py`

**Model**: sonnet

- [ ] **Step 1: 실패하는 테스트 작성**

**수정 후** (new file: `tests/test_crosscheck.py`):
```python
from dartweave.parse.relation import EdgeType, RelationEdge, Source
from dartweave.trust.crosscheck import CrossResult, cross_check_structured


def _sh(holder_name, target, pct, rcept="20250311000001", as_of="20241231"):
    return RelationEdge(
        edge_type=EdgeType.MAJOR_SHAREHOLDER_OF,
        source_name=holder_name,
        source_corp_code=None,
        target_name=None,
        target_corp_code=target,
        rcept_no=rcept,
        fiscal_year=rcept[:4],
        as_of=as_of,
        source=Source.STRUCTURED,
        share_pct=pct,
        reporter_corp_code=target,
    )


def _inv(holder, target_name, pct, rcept="20250311000002", as_of="20241231"):
    return RelationEdge(
        edge_type=EdgeType.INVESTS_IN,
        source_name="",
        source_corp_code=holder,
        target_name=target_name,
        target_corp_code=None,
        rcept_no=rcept,
        fiscal_year=rcept[:4],
        as_of=as_of,
        source=Source.STRUCTURED,
        share_pct=pct,
        reporter_corp_code=holder,
    )


NAME_TO_CODE = {"삼성생명보험": "001", "에이사": "002"}
CODE_TO_NAME = {"001": "삼성생명보험", "002": "에이사"}


def test_matching_pair_is_confirmed():
    res = cross_check_structured(
        [_sh("삼성생명보험", "002", 30.0)],
        [_inv("001", "에이사", 30.0)],
        NAME_TO_CODE,
        CODE_TO_NAME,
    )
    assert res[0].status is CrossResult.CONFIRMED


def test_value_gap_in_same_scope_is_conflict():
    res = cross_check_structured(
        [_sh("삼성생명보험", "002", 30.0)],
        [_inv("001", "에이사", 25.0)],
        NAME_TO_CODE,
        CODE_TO_NAME,
    )
    assert res[0].status is CrossResult.CONFLICT
    assert res[0].detail["gap"] == 5.0


def test_different_scope_is_change_not_conflict():
    res = cross_check_structured(
        [_sh("삼성생명보험", "002", 30.0, rcept="20240311000001", as_of="20231231")],
        [_inv("001", "에이사", 25.0)],
        NAME_TO_CODE,
        CODE_TO_NAME,
    )
    assert res[0].status is CrossResult.CHANGE


def test_no_counterpart_is_single_source():
    res = cross_check_structured(
        [_sh("삼성생명보험", "002", 30.0)], [], NAME_TO_CODE, CODE_TO_NAME
    )
    assert res[0].status is CrossResult.SINGLE
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_crosscheck.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dartweave.trust.crosscheck'`

- [ ] **Step 3: 구현**

**수정 후** (new file: `src/dartweave/trust/crosscheck.py`):
```python
"""정형 ↔ 정형 교차확인.

A사 「최대주주 현황」 과 B사 「타법인 출자현황」 은 같은 사실을 반대편에서 신고한 것이다.
둘이 어긋나면 **둘 다 법정 신고 항목이라 변명이 불가능하다** — 이게 1급 모순이다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from dartweave.parse.relation import RelationEdge
from dartweave.trust.scope import Verdict, compare_scope


class CrossResult(Enum):
    CONFIRMED = "confirmed"
    CONFLICT = "conflict"
    CHANGE = "change"
    SINGLE = "single"


@dataclass(frozen=True)
class CrossCheck:
    edge: RelationEdge
    status: CrossResult
    counterpart_rcept_no: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)


def _pair_key(holder_code: str, target_code: str) -> tuple[str, str]:
    return (holder_code, target_code)


def cross_check_structured(
    shareholder_edges: list[RelationEdge],
    investment_edges: list[RelationEdge],
    name_to_code: dict[str, str],
    code_to_name: dict[str, str],
) -> list[CrossCheck]:
    """최대주주 현황(보유자=이름) ↔ 타법인 출자현황(피출자=이름) 을 맞댄다."""
    index: dict[tuple[str, str], RelationEdge] = {}
    for inv in investment_edges:
        holder = inv.source_corp_code or ""
        target = name_to_code.get(inv.target_name or "", "")
        if holder and target:
            index[_pair_key(holder, target)] = inv

    results: list[CrossCheck] = []
    for sh in shareholder_edges:
        holder = name_to_code.get(sh.source_name, "")
        target = sh.target_corp_code or ""
        counterpart = index.get(_pair_key(holder, target)) if holder else None

        if counterpart is None:
            results.append(CrossCheck(sh, CrossResult.SINGLE))
            continue

        verdict = compare_scope(sh, counterpart)
        if verdict is Verdict.CHANGE:
            status = CrossResult.CHANGE
            detail: dict[str, Any] = {
                "from_fiscal_year": counterpart.fiscal_year,
                "to_fiscal_year": sh.fiscal_year,
            }
        elif verdict is Verdict.AGREE:
            status = CrossResult.CONFIRMED
            detail = {}
        else:
            status = CrossResult.CONFLICT
            gap = None
            if sh.share_pct is not None and counterpart.share_pct is not None:
                gap = round(abs(sh.share_pct - counterpart.share_pct), 6)
            detail = {
                "reported_by_target": sh.share_pct,
                "reported_by_holder": counterpart.share_pct,
                "gap": gap,
            }
        results.append(
            CrossCheck(sh, status, counterpart.rcept_no, detail)
        )
    return results
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_crosscheck.py -v`
Expected: PASS — 4 passed

- [ ] **Step 5: 커밋**

```bash
git add src/dartweave/trust/crosscheck.py tests/test_crosscheck.py
git commit -m "feat: 정형↔정형 교차확인 (CONFIRMED/CONFLICT/CHANGE/SINGLE 4상태)"
```

---

### Task 16: evidence_weight 파생 계산

**Files:**
- Create: `src/dartweave/trust/weight.py`
- Test: `tests/test_weight.py`

**Model**: sonnet

> D5 — 값을 저장하지 않고 인자에서 파생한다. 실측 정확도 표가 갱신되면 전수 UPDATE 없이 전체가 갱신되어야 한다.

- [ ] **Step 1: 실패하는 테스트 작성**

**수정 후** (new file: `tests/test_weight.py`):
```python
import pytest

from dartweave.trust.weight import (
    Coefficients,
    Grade,
    WeightInputs,
    evidence_weight,
    grade_of,
    summarize,
)


def _inp(**kw):
    base = dict(
        is_structured=True,
        confidence=None,
        cross_confirmed=False,
        mention_count=1,
        share_pct=None,
        observed_precision=None,
    )
    base.update(kw)
    return WeightInputs(**base)


def test_structured_edge_gets_full_source_weight():
    assert evidence_weight(_inp()) == pytest.approx(1.0)


def test_text_edge_uses_observed_precision_not_raw_confidence():
    """AC-4c — 모델이 주장한 confidence 가 산식에 직접 들어가면 안 된다."""
    w = evidence_weight(
        _inp(is_structured=False, confidence=0.95, observed_precision=0.70)
    )
    assert w == pytest.approx(0.70)


def test_text_edge_without_observed_precision_falls_back_conservatively():
    w = evidence_weight(_inp(is_structured=False, confidence=0.95))
    assert w == pytest.approx(Coefficients().unmeasured_text_weight)
    assert w < 0.95, "미측정 구간을 모델 주장값으로 채우면 안 됨"


def test_cross_confirmed_increases_weight():
    assert evidence_weight(_inp(cross_confirmed=True)) > evidence_weight(_inp())


def test_mention_count_is_capped():
    high = evidence_weight(_inp(mention_count=50))
    mid = evidence_weight(_inp(mention_count=6))
    assert high == pytest.approx(mid)


def test_share_pct_scales_quantitative_edges():
    assert evidence_weight(_inp(share_pct=50.0)) < evidence_weight(_inp(share_pct=100.0))


def test_grade_mapping():
    assert grade_of(_inp(cross_confirmed=True)) is Grade.T1
    assert grade_of(_inp()) is Grade.T2
    assert grade_of(_inp(is_structured=False)) is Grade.T3


def test_summarize_reports_distribution_and_conflicts():
    s = summarize(
        [_inp(cross_confirmed=True), _inp(), _inp(is_structured=False)],
        conflict_count=2,
    )
    assert s["T1"] == pytest.approx(1 / 3)
    assert s["T2"] == pytest.approx(1 / 3)
    assert s["T3"] == pytest.approx(1 / 3)
    assert s["conflicts"] == 2
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_weight.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dartweave.trust.weight'`

- [ ] **Step 3: 구현**

**수정 후** (new file: `src/dartweave/trust/weight.py`):
```python
"""evidence_weight 파생 계산.

D5 — 값을 저장하지 않는다. 인자만 저장하고 여기서 계산한다.
정밀도 검수를 더 하면 observed_precision 이 좋아지고, 그때 전수 UPDATE 없이
모든 엣지 가중치가 갱신되어야 하기 때문이다.

계수는 임의값이므로 클래스로 분리한다 — 층1의 민감도 스윕이 이걸 흔든다.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


@dataclass(frozen=True)
class Coefficients:
    cross_confirm_bonus: float = 1.5
    mention_step: float = 0.1
    mention_cap: float = 1.5
    unmeasured_text_weight: float = 0.5


@dataclass(frozen=True)
class WeightInputs:
    is_structured: bool
    confidence: float | None
    cross_confirmed: bool
    mention_count: int
    share_pct: float | None
    observed_precision: float | None


class Grade(Enum):
    T1 = "T1"
    T2 = "T2"
    T3 = "T3"


def evidence_weight(x: WeightInputs, coef: Coefficients | None = None) -> float:
    c = coef or Coefficients()

    # 겹2-a 출처: 정형은 1.0, 본문은 '우리가 측정한' 정확도. 모델 주장값은 안 쓴다.
    if x.is_structured:
        w = 1.0
    elif x.observed_precision is not None:
        w = x.observed_precision
    else:
        w = c.unmeasured_text_weight

    # 겹2-b 교차확인
    if x.cross_confirmed:
        w *= c.cross_confirm_bonus

    # 겹2-c 반복 언급 (출처 주체 기준으로 이미 집계됨)
    w *= min(1 + c.mention_step * (max(x.mention_count, 1) - 1), c.mention_cap)

    # 겹3 정량속성: 값이 있을 때만. 없는 값을 추정하지 않는다.
    if x.share_pct is not None:
        w *= x.share_pct / 100

    return w


def grade_of(x: WeightInputs) -> Grade:
    if x.cross_confirmed:
        return Grade.T1
    return Grade.T2 if x.is_structured else Grade.T3


def summarize(inputs: list[WeightInputs], *, conflict_count: int) -> dict[str, float]:
    """AC-8 — 한 줄 요약: T1 x% · T2 y% · T3 z% · 충돌 n건."""
    total = len(inputs) or 1
    counts = {g: 0 for g in Grade}
    for x in inputs:
        counts[grade_of(x)] += 1
    result: dict[str, float] = {g.value: counts[g] / total for g in Grade}
    result["conflicts"] = conflict_count
    return result
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_weight.py -v`
Expected: PASS — 8 passed

- [ ] **Step 5: 커밋**

```bash
git add src/dartweave/trust/weight.py tests/test_weight.py
git commit -m "feat: evidence_weight 파생 계산 (실측 정확도 사용, 계수 분리로 스윕 대비)"
```

---

### Task 17: 모순 A 검출 (지분 합계 규칙 위반)

**Files:**
- Create: `src/dartweave/trust/contradiction.py`
- Test: `tests/test_contradiction.py`

**Model**: sonnet

- [ ] **Step 1: 실패하는 테스트 작성**

**수정 후** (new file: `tests/test_contradiction.py`):
```python
from dartweave.parse.relation import EdgeType, RelationEdge, Source
from dartweave.trust.contradiction import detect_grade_a


def _sh(holder, target, pct, rcept="20250311000001", as_of="20241231"):
    return RelationEdge(
        edge_type=EdgeType.MAJOR_SHAREHOLDER_OF,
        source_name=holder,
        source_corp_code=None,
        target_name=None,
        target_corp_code=target,
        rcept_no=rcept,
        fiscal_year=rcept[:4],
        as_of=as_of,
        source=Source.STRUCTURED,
        share_pct=pct,
    )


def test_detects_sum_over_100():
    findings = detect_grade_a([_sh("A", "X", 51.0), _sh("B", "X", 37.3), _sh("C", "X", 30.0)])
    assert len(findings) == 1
    assert findings[0].detail["total"] == 118.3
    assert findings[0].grade == "A"


def test_normal_sum_is_not_flagged():
    assert detect_grade_a([_sh("A", "X", 51.0), _sh("B", "X", 30.0)]) == []


def test_tolerance_absorbs_rounding():
    """100.3 은 반올림 누적일 수 있다. 이걸 띄우면 오탐이 쏟아진다."""
    assert detect_grade_a([_sh("A", "X", 50.2), _sh("B", "X", 50.1)]) == []


def test_different_scopes_are_summed_separately():
    """다른 기준일끼리 합치면 정상 기업이 전부 위반으로 나온다."""
    edges = [
        _sh("A", "X", 60.0, rcept="20240311000001", as_of="20231231"),
        _sh("B", "X", 60.0, rcept="20250311000001", as_of="20241231"),
    ]
    assert detect_grade_a(edges) == []


def test_missing_share_pct_is_ignored_not_zero():
    findings = detect_grade_a([_sh("A", "X", None), _sh("B", "X", 99.0)])
    assert findings == []
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_contradiction.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dartweave.trust.contradiction'`

- [ ] **Step 3: 구현**

**수정 후** (new file: `src/dartweave/trust/contradiction.py`):
```python
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

SUM_TOLERANCE = 0.5  # 반올림 누적 흡수. 이보다 좁히면 오탐이 쏟아진다.


@dataclass(frozen=True)
class Finding:
    grade: str
    edge_key: str
    detail: dict[str, Any]


def detect_grade_a(edges: list[RelationEdge]) -> list[Finding]:
    """지분 합계 > 100% — 같은 (대상, 스코프) 안에서만 합산한다."""
    buckets: dict[tuple[str, tuple[str, str]], list[RelationEdge]] = defaultdict(list)
    for e in edges:
        if e.edge_type is not EdgeType.MAJOR_SHAREHOLDER_OF:
            continue
        if e.share_pct is None:
            continue  # 미상은 0으로 치면 안 된다
        buckets[(e.target_corp_code or "", scope_key(e))].append(e)

    findings: list[Finding] = []
    for (target, scope), group in buckets.items():
        total = round(sum(e.share_pct or 0.0 for e in group), 6)
        if total <= 100.0 + SUM_TOLERANCE:
            continue
        findings.append(
            Finding(
                grade="A",
                edge_key=f"{target}|SHARE_SUM|{scope[0]}:{scope[1]}",
                detail={
                    "target_corp_code": target,
                    "fiscal_year": scope[0],
                    "as_of": scope[1],
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
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_contradiction.py -v`
Expected: PASS — 5 passed

- [ ] **Step 5: 커밋**

```bash
git add src/dartweave/trust/contradiction.py tests/test_contradiction.py
git commit -m "feat: 모순 등급 A 검출 (스코프별 합산, 반올림 허용치, 미상은 0 아님)"
```

---

### Task 18: Neo4j 스키마 (제약 · 인덱스)

**Files:**
- Create: `src/dartweave/graph/__init__.py` · `src/dartweave/graph/schema.py`
- Test: `tests/test_graph_schema.py`

**Model**: sonnet

- [ ] **Step 1: 실패하는 테스트 작성**

**수정 후** (new file: `tests/test_graph_schema.py`):
```python
from dartweave.graph.schema import CONSTRAINTS, INDEXES, REQUIRED_EDGE_PROPS


def test_company_corp_code_is_unique():
    assert any("Company" in c and "corp_code" in c and "UNIQUE" in c.upper() for c in CONSTRAINTS)


def test_rcept_no_is_indexed_for_provenance_lookup():
    joined = " ".join(INDEXES)
    assert "rcept_no" in joined


def test_required_edge_props_match_ac3():
    assert REQUIRED_EDGE_PROPS == (
        "rcept_no",
        "as_of",
        "fiscal_year",
        "source",
        "mention_count",
    )


def test_all_statements_are_idempotent():
    for stmt in CONSTRAINTS + INDEXES:
        assert "IF NOT EXISTS" in stmt.upper(), f"재실행 불가: {stmt}"
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_graph_schema.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dartweave.graph'`

- [ ] **Step 3: 구현**

**수정 후** (new file: `src/dartweave/graph/__init__.py`):
```python
__all__ = ["schema"]
```

**수정 후** (new file: `src/dartweave/graph/schema.py`):
```python
"""Neo4j 스키마. 모든 문장은 재실행 가능해야 한다 (IF NOT EXISTS)."""
from __future__ import annotations

# AC-3 — 이 다섯은 모든 엣지가 반드시 갖는다
REQUIRED_EDGE_PROPS: tuple[str, ...] = (
    "rcept_no",
    "as_of",
    "fiscal_year",
    "source",
    "mention_count",
)

CONSTRAINTS: list[str] = [
    "CREATE CONSTRAINT company_corp_code IF NOT EXISTS "
    "FOR (c:Company) REQUIRE c.corp_code IS UNIQUE",
    "CREATE CONSTRAINT person_key IF NOT EXISTS "
    "FOR (p:Person) REQUIRE p.key IS UNIQUE",
    "CREATE CONSTRAINT auditor_name IF NOT EXISTS "
    "FOR (a:Auditor) REQUIRE a.name IS UNIQUE",
]

INDEXES: list[str] = [
    "CREATE INDEX company_name IF NOT EXISTS FOR (c:Company) ON (c.name)",
    "CREATE INDEX rel_rcept_shareholder IF NOT EXISTS "
    "FOR ()-[r:MAJOR_SHAREHOLDER_OF]-() ON (r.rcept_no)",
    "CREATE INDEX rel_rcept_invests IF NOT EXISTS "
    "FOR ()-[r:INVESTS_IN]-() ON (r.rcept_no)",
    "CREATE INDEX rel_rcept_holds IF NOT EXISTS "
    "FOR ()-[r:HOLDS_5PCT]-() ON (r.rcept_no)",
]


def apply_schema(session) -> None:
    for stmt in CONSTRAINTS + INDEXES:
        session.run(stmt)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_graph_schema.py -v`
Expected: PASS — 4 passed

- [ ] **Step 5: 커밋**

```bash
git add src/dartweave/graph tests/test_graph_schema.py
git commit -m "feat: Neo4j 제약·인덱스 (전부 IF NOT EXISTS, 필수 엣지 속성 5종 명시)"
```

---

### Task 19: 멱등 적재 (Cypher 생성)

**Files:**
- Create: `src/dartweave/graph/load.py`
- Test: `tests/test_graph_load.py`

**Model**: sonnet

- [ ] **Step 1: 실패하는 테스트 작성**

**수정 후** (new file: `tests/test_graph_load.py`):
```python
import pytest

from dartweave.graph.load import build_edge_merge
from dartweave.graph.schema import REQUIRED_EDGE_PROPS
from dartweave.parse.relation import EdgeType, RelationEdge, Source


def _edge(**kw):
    base = dict(
        edge_type=EdgeType.MAJOR_SHAREHOLDER_OF,
        source_name="삼성생명보험",
        source_corp_code="001",
        target_name=None,
        target_corp_code="002",
        rcept_no="20250311000001",
        fiscal_year="2025",
        as_of="20241231",
        source=Source.STRUCTURED,
        share_pct=8.51,
    )
    base.update(kw)
    return RelationEdge(**base)


def test_uses_merge_not_create():
    cypher, _ = build_edge_merge(_edge(), mention_count=1)
    assert "MERGE" in cypher and "CREATE (" not in cypher


def test_merge_key_includes_fiscal_year_and_source():
    """재적재가 중복을 만들지 않도록 복합 키를 쓴다."""
    cypher, _ = build_edge_merge(_edge(), mention_count=1)
    assert "fiscal_year" in cypher and "source" in cypher


def test_all_required_props_present_in_params():
    _, params = build_edge_merge(_edge(), mention_count=3)
    for prop in REQUIRED_EDGE_PROPS:
        assert prop in params, f"필수 속성 누락: {prop}"
    assert params["mention_count"] == 3


def test_evidence_weight_is_not_persisted():
    """D5 — weight 는 저장하지 않는다. 인자만 저장한다."""
    cypher, params = build_edge_merge(_edge(), mention_count=1)
    assert "evidence_weight" not in cypher
    assert "evidence_weight" not in params


def test_edge_without_resolvable_target_raises():
    """미해소를 신규 노드로 조용히 만드는 경로가 없어야 한다 (AC-10)."""
    with pytest.raises(ValueError, match="해소"):
        build_edge_merge(_edge(target_corp_code=None, target_name="미상회사"), mention_count=1)
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_graph_load.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dartweave.graph.load'`

- [ ] **Step 3: 구현**

**수정 후** (new file: `src/dartweave/graph/load.py`):
```python
"""멱등 적재용 Cypher 생성.

- MERGE 복합 키: (시작, 끝, 타입, fiscal_year, source) — 재적재가 중복을 만들지 않는다
- evidence_weight 는 저장하지 않는다 (D5). 인자만 남기고 투영 직전 계산한다
- 해소되지 않은 대상은 노드를 만들지 않고 예외로 막는다 (AC-10)
"""
from __future__ import annotations

from typing import Any

from dartweave.parse.relation import EdgeType, RelationEdge

_COMPANY_TARGET_TYPES = {
    EdgeType.MAJOR_SHAREHOLDER_OF,
    EdgeType.INVESTS_IN,
    EdgeType.HOLDS_5PCT,
}


def _require(value: str | None, what: str, edge: RelationEdge) -> str:
    if not value:
        raise ValueError(
            f"{what} 가 해소되지 않았습니다 ({edge.edge_type.value}, {edge.rcept_no}). "
            "미해소는 대기열로 보내야 하며 신규 노드를 만들지 않습니다."
        )
    return value


def build_edge_merge(
    edge: RelationEdge, *, mention_count: int
) -> tuple[str, dict[str, Any]]:
    # 양쪽 모두 해소된 corp_code 를 요구한다. 슬라이스 1의 엣지는 전부 Company↔Company 다.
    start_code = _require(edge.source_corp_code, "시작 노드", edge)
    end_code = _require(edge.target_corp_code, "끝 노드", edge)

    cypher = f"""
    MATCH (a:Company {{corp_code: $start_code}})
    MATCH (b:Company {{corp_code: $end_code}})
    MERGE (a)-[r:{edge.edge_type.value} {{
        fiscal_year: $fiscal_year,
        source: $source,
        as_of: $as_of
    }}]->(b)
    SET r.rcept_no = $rcept_no,
        r.mention_count = $mention_count,
        r.share_pct = $share_pct,
        r.confidence = $confidence,
        r.cross_confirmed = $cross_confirmed,
        r.counterpart_rcept_no = $counterpart_rcept_no
    RETURN r
    """.strip()

    params: dict[str, Any] = {
        "start_code": start_code,
        "end_code": end_code,
        "rcept_no": edge.rcept_no,
        "as_of": edge.as_of,
        "fiscal_year": edge.fiscal_year,
        "source": edge.source.value,
        "mention_count": mention_count,
        "share_pct": edge.share_pct,
        "confidence": edge.confidence,
        "cross_confirmed": False,
        "counterpart_rcept_no": None,
    }
    return cypher, params
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_graph_load.py -v`
Expected: PASS — 5 passed

- [ ] **Step 5: 커밋**

```bash
git add src/dartweave/graph/load.py tests/test_graph_load.py
git commit -m "feat: 멱등 적재 Cypher (복합 MERGE 키, weight 비저장, 미해소 노드생성 차단)"
```

---

### Task 20: 엣지 내보내기 (셔플 · CPM · 대체 경로용)

**Files:**
- Create: `src/dartweave/graph/export.py`
- Test: `tests/test_graph_export.py`

**Model**: sonnet

> AC-9 — 이 경로가 세 목적을 겸한다: 차수 보존 귀무모형 / CPM 재실행 / GDS 대체.

- [ ] **Step 1: 실패하는 테스트 작성**

**수정 후** (new file: `tests/test_graph_export.py`):
```python
import csv
import io

from dartweave.graph.export import EXPORT_HEADER, degree_table, write_edge_list


ROWS = [
    {"start": "A", "end": "B", "type": "SUPPLIES_TO", "weight": 1.0, "fiscal_year": "2025"},
    {"start": "B", "end": "C", "type": "SUPPLIES_TO", "weight": 0.5, "fiscal_year": "2025"},
    {"start": "A", "end": "C", "type": "SUPPLIES_TO", "weight": 2.0, "fiscal_year": "2025"},
]


def test_header_matches_contract():
    assert EXPORT_HEADER == ["start", "end", "type", "weight", "fiscal_year"]


def test_writes_all_rows_with_header():
    buf = io.StringIO()
    write_edge_list(ROWS, buf)
    parsed = list(csv.reader(io.StringIO(buf.getvalue())))
    assert parsed[0] == EXPORT_HEADER
    assert len(parsed) == 4


def test_degree_table_preserves_direction():
    """차수 보존 셔플이 가능하려면 방향별 차수가 나와야 한다."""
    deg = degree_table(ROWS)
    assert deg["A"] == {"out": 2, "in": 0}
    assert deg["B"] == {"out": 1, "in": 1}
    assert deg["C"] == {"out": 0, "in": 2}


def test_degree_sum_is_conserved():
    deg = degree_table(ROWS)
    assert sum(d["out"] for d in deg.values()) == len(ROWS)
    assert sum(d["in"] for d in deg.values()) == len(ROWS)
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_graph_export.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dartweave.graph.export'`

- [ ] **Step 3: 구현**

**수정 후** (new file: `src/dartweave/graph/export.py`):
```python
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
```

- [ ] **Step 4: 전체 테스트 통과 확인**

Run: `uv run pytest -v`
Expected: PASS — 전체 스위트 통과

- [ ] **Step 5: 커밋**

```bash
git add src/dartweave/graph/export.py tests/test_graph_export.py
git commit -m "feat: 엣지 목록 내보내기 + 방향별 차수표 (귀무모형·CPM·대체경로 겸용)"
```

---

### Task 21: 엔티티 해소 (이름 → corp_code)

**Files:**
- Create: `src/dartweave/resolve/__init__.py` · `src/dartweave/resolve/normalize.py` · `src/dartweave/resolve/resolver.py`
- Test: `tests/test_resolve.py`

**Model**: sonnet

> 정형 API도 관계 상대를 이름으로만 준다. 해소가 틀리면 교차확인이 실패하고 T1이 T2/T3로 강등된다.

- [ ] **Step 1: 실패하는 테스트 작성**

**수정 후** (new file: `tests/test_resolve.py`):
```python
from dartweave.resolve.normalize import normalize_name
from dartweave.resolve.resolver import Resolution, Resolver


def test_normalize_strips_corporate_suffix():
    assert normalize_name("삼성전자(주)") == "삼성전자"
    assert normalize_name("(주)삼성전자") == "삼성전자"
    assert normalize_name("삼성전자주식회사") == "삼성전자"


def test_normalize_collapses_whitespace_and_case():
    assert normalize_name("  SK   하이닉스 ") == "sk하이닉스"
    assert normalize_name("Samsung Electronics") == "samsungelectronics"


def test_resolves_via_official_name():
    r = Resolver({"삼성전자": "00126380"}, aliases={})
    res = r.resolve("삼성전자(주)", rcept_no="20250311000001")
    assert res.corp_code == "00126380"
    assert res.status is Resolution.RESOLVED


def test_resolves_via_alias_dictionary():
    r = Resolver({"삼성전자": "00126380"}, aliases={"samsungelectronics": "00126380"})
    assert r.resolve("Samsung Electronics", rcept_no="x").corp_code == "00126380"


def test_unresolved_returns_none_and_is_queued():
    r = Resolver({"삼성전자": "00126380"}, aliases={})
    res = r.resolve("듣보잡회사", rcept_no="20250311000001")
    assert res.corp_code is None
    assert res.status is Resolution.UNRESOLVED
    assert r.unresolved[0].surface_form == "듣보잡회사"


def test_resolution_rate_is_reported():
    r = Resolver({"삼성전자": "00126380"}, aliases={})
    r.resolve("삼성전자", rcept_no="x")
    r.resolve("삼성전자", rcept_no="x")
    r.resolve("모르는회사", rcept_no="x")
    assert r.resolution_rate() == 2 / 3


def test_never_invents_a_corp_code():
    """AC-10 — 미해소를 신규 코드로 조용히 만드는 경로가 없어야 한다."""
    r = Resolver({}, aliases={})
    assert r.resolve("무엇이든", rcept_no="x").corp_code is None
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_resolve.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dartweave.resolve'`

- [ ] **Step 3: 구현**

**수정 후** (new file: `src/dartweave/resolve/__init__.py`):
```python
__all__ = ["normalize", "resolver"]
```

**수정 후** (new file: `src/dartweave/resolve/normalize.py`):
```python
"""기업명 표기 정규화. 해소의 1단계."""
from __future__ import annotations

import re

_SUFFIXES = ("주식회사", "(주)", "㈜", "유한회사", "co.,ltd", "co.ltd", "ltd", "inc")
_WS = re.compile(r"\s+")


def normalize_name(raw: str) -> str:
    text = _WS.sub("", str(raw or "")).lower()
    changed = True
    while changed:
        changed = False
        for suffix in _SUFFIXES:
            s = suffix.replace(" ", "").lower()
            if text.startswith(s):
                text, changed = text[len(s) :], True
            if text.endswith(s):
                text, changed = text[: -len(s)], True
    return text
```

**수정 후** (new file: `src/dartweave/resolve/resolver.py`):
```python
"""이름 → corp_code 해소.

원칙 (AC-10): **미해소는 신규 노드를 만들지 않는다.** 대기열로 보내고 센다.
침묵 생성이 그래프 오염의 가장 흔한 경로다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from dartweave.resolve.normalize import normalize_name


class Resolution(Enum):
    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class ResolveResult:
    surface_form: str
    corp_code: str | None
    status: Resolution


@dataclass
class UnresolvedRecord:
    surface_form: str
    rcept_no: str
    occurrences: int = 1


@dataclass
class Resolver:
    official: dict[str, str]
    aliases: dict[str, str]
    unresolved: list[UnresolvedRecord] = field(default_factory=list)
    _attempts: int = 0
    _hits: int = 0

    def __post_init__(self) -> None:
        self._by_norm = {normalize_name(k): v for k, v in self.official.items()}

    def resolve(self, surface_form: str, *, rcept_no: str) -> ResolveResult:
        self._attempts += 1
        key = normalize_name(surface_form)
        code = self._by_norm.get(key) or self.aliases.get(key)
        if code:
            self._hits += 1
            return ResolveResult(surface_form, code, Resolution.RESOLVED)

        for rec in self.unresolved:
            if rec.surface_form == surface_form:
                rec.occurrences += 1
                break
        else:
            self.unresolved.append(UnresolvedRecord(surface_form, rcept_no))
        return ResolveResult(surface_form, None, Resolution.UNRESOLVED)

    def resolution_rate(self) -> float:
        return self._hits / self._attempts if self._attempts else 0.0
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_resolve.py -v`
Expected: PASS — 7 passed

- [ ] **Step 5: 커밋**

```bash
git add src/dartweave/resolve tests/test_resolve.py
git commit -m "feat: 엔티티 해소 (표기 정규화 + 별칭 + 미해소 대기열, 코드 날조 금지)"
```

---

### Task 22: Postgres 원장 쓰기 (멱등 upsert)

**Files:**
- Create: `src/dartweave/db/session.py` · `src/dartweave/db/ledger.py`
- Test: `tests/test_ledger.py`

**Model**: sonnet

- [ ] **Step 1: 실패하는 테스트 작성**

**수정 후** (new file: `tests/test_ledger.py`):
```python
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from dartweave.dart.disclosure import DisclosureRow
from dartweave.db.ledger import upsert_companies, upsert_disclosures
from dartweave.db.models import Base, Company, Disclosure
from dartweave.select.targets import SelectedCompany


@pytest.fixture
def session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def test_upsert_company_records_reason(session):
    upsert_companies(session, [SelectedCompany("001", "에이사", "26110", "업종코드 부합")])
    row = session.get(Company, "001")
    assert row.selected is True
    assert row.select_reason == "업종코드 부합"


def test_upsert_company_is_idempotent(session):
    picked = [SelectedCompany("001", "에이사", "26110", "업종코드 부합")]
    upsert_companies(session, picked)
    upsert_companies(session, picked)
    assert len(session.scalars(select(Company)).all()) == 1


def test_upsert_disclosure_is_idempotent(session):
    rows = [DisclosureRow("20250311000001", "001", "사업보고서", "20250311", "2025")]
    upsert_disclosures(session, rows)
    upsert_disclosures(session, rows)
    assert len(session.scalars(select(Disclosure)).all()) == 1


def test_failure_reason_is_persisted(session):
    upsert_disclosures(
        session,
        [DisclosureRow("20250311000002", "001", "사업보고서", "20250311", "2025")],
        fetch_status="failed",
        fail_reason="원문 ZIP 404",
    )
    row = session.get(Disclosure, "20250311000002")
    assert row.fetch_status == "failed"
    assert row.fail_reason == "원문 ZIP 404"
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_ledger.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dartweave.db.ledger'`

- [ ] **Step 3: 구현**

**수정 후** (new file: `src/dartweave/db/session.py`):
```python
"""Postgres 세션 팩토리."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from dartweave.config import Settings
from dartweave.db.models import Base


def make_engine(settings: Settings | None = None):
    s = settings or Settings.from_env()
    return create_engine(s.pg_dsn, pool_pre_ping=True)


def init_schema(engine) -> None:
    Base.metadata.create_all(engine)


@contextmanager
def session_scope(engine) -> Iterator[Session]:
    with Session(engine) as s:
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
```

**수정 후** (new file: `src/dartweave/db/ledger.py`):
```python
"""원장 멱등 upsert. 재실행이 중복을 만들지 않아야 재개가 성립한다."""
from __future__ import annotations

from sqlalchemy.orm import Session

from dartweave.dart.disclosure import DisclosureRow
from dartweave.db.models import Company, Disclosure
from dartweave.select.targets import SelectedCompany


def upsert_companies(session: Session, picked: list[SelectedCompany]) -> int:
    for p in picked:
        row = session.get(Company, p.corp_code)
        if row is None:
            row = Company(corp_code=p.corp_code, corp_name=p.corp_name)
            session.add(row)
        row.corp_name = p.corp_name
        row.induty_code = p.induty_code
        row.selected = True
        row.select_reason = p.reason  # AC-1 — 사유 없는 선정을 남기지 않는다
    session.flush()
    return len(picked)


def upsert_disclosures(
    session: Session,
    rows: list[DisclosureRow],
    *,
    fetch_status: str = "pending",
    fail_reason: str | None = None,
) -> int:
    for r in rows:
        row = session.get(Disclosure, r.rcept_no)
        if row is None:
            row = Disclosure(rcept_no=r.rcept_no, corp_code=r.corp_code)
            session.add(row)
        row.corp_code = r.corp_code
        row.report_nm = r.report_nm
        row.rcept_dt = r.rcept_dt
        row.fiscal_year = r.fiscal_year
        row.fetch_status = fetch_status
        row.fail_reason = fail_reason  # AC-2 — 실패를 침묵으로 넘기지 않는다
    session.flush()
    return len(rows)
```

- [ ] **Step 4: sqlite 드라이버 추가 후 테스트 통과 확인**

Run: `uv add --dev pysqlite3-binary || true; uv run pytest tests/test_ledger.py -v`
Expected: PASS — 4 passed (`sqlite+pysqlite` 는 CPython 표준 `sqlite3` 로 동작하므로 추가 설치가 실패해도 무방)

- [ ] **Step 5: 커밋**

```bash
git add src/dartweave/db/session.py src/dartweave/db/ledger.py tests/test_ledger.py
git commit -m "feat: 원장 멱등 upsert (선정사유·실패사유 영속, 재실행 안전)"
```

---

### Task 23: 파이프라인 CLI (단계별 실행 + 체크포인트)

**Files:**
- Create: `src/dartweave/pipeline.py` · `scripts/run_stage.py`
- Test: `tests/test_pipeline.py`

**Model**: sonnet

> D4 — Celery 없이 스크립트 + 원장 체크포인트로 재개한다.

- [ ] **Step 1: 실패하는 테스트 작성**

**수정 후** (new file: `tests/test_pipeline.py`):
```python
import pytest

from dartweave.pipeline import STAGES, Stage, resolve_stage, stages_from


def test_stage_order_is_fixed():
    assert [s.value for s in STAGES] == [
        "select",
        "collect",
        "parse",
        "resolve",
        "load",
        "trust",
        "export",
    ]


def test_resolve_stage_accepts_name():
    assert resolve_stage("load") is Stage.LOAD


def test_unknown_stage_raises_with_available_list():
    with pytest.raises(ValueError) as ei:
        resolve_stage("nope")
    assert "select" in str(ei.value)


def test_stages_from_returns_suffix():
    assert stages_from(Stage.LOAD) == [Stage.LOAD, Stage.TRUST, Stage.EXPORT]


def test_stages_from_first_returns_all():
    assert stages_from(Stage.SELECT) == list(STAGES)
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_pipeline.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dartweave.pipeline'`

- [ ] **Step 3: 구현**

**수정 후** (new file: `src/dartweave/pipeline.py`):
```python
"""파이프라인 단계 정의.

각 단계는 독립 실행 가능하고, 앞 단계가 실패해도 뒤 단계가 이미 만든
산출물은 살아남는다. 재개 기준점은 Postgres 원장이다 (D4).
"""
from __future__ import annotations

from enum import Enum


class Stage(Enum):
    SELECT = "select"
    COLLECT = "collect"
    PARSE = "parse"
    RESOLVE = "resolve"
    LOAD = "load"
    TRUST = "trust"
    EXPORT = "export"


STAGES: tuple[Stage, ...] = (
    Stage.SELECT,
    Stage.COLLECT,
    Stage.PARSE,
    Stage.RESOLVE,
    Stage.LOAD,
    Stage.TRUST,
    Stage.EXPORT,
)


def resolve_stage(name: str) -> Stage:
    for s in STAGES:
        if s.value == name:
            return s
    available = ", ".join(s.value for s in STAGES)
    raise ValueError(f"알 수 없는 단계 '{name}'. 가능한 값: {available}")


def stages_from(start: Stage) -> list[Stage]:
    idx = STAGES.index(start)
    return list(STAGES[idx:])
```

**수정 후** (new file: `scripts/run_stage.py`):
```python
"""단계 실행 엔트리.

사용:
    uv run python scripts/run_stage.py --from load
    uv run python scripts/run_stage.py --only export

DART_API_KEY 가 필요한 단계(select/collect)는 키가 없으면 명확히 중단한다.
"""
from __future__ import annotations

import argparse
import sys

from dartweave.config import Settings
from dartweave.db.session import init_schema, make_engine
from dartweave.pipeline import Stage, resolve_stage, stages_from

NEEDS_API_KEY = {Stage.SELECT, Stage.COLLECT}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--from", dest="start", help="이 단계부터 끝까지")
    group.add_argument("--only", dest="only", help="이 단계만")
    args = parser.parse_args(argv)

    settings = Settings.from_env()
    targets = (
        [resolve_stage(args.only)]
        if args.only
        else stages_from(resolve_stage(args.start))
    )

    if any(s in NEEDS_API_KEY for s in targets) and not settings.dart_api_key:
        print(
            "DART_API_KEY 가 없어 select/collect 를 실행할 수 없습니다.\n"
            "  - 키 발급: https://opendart.fss.or.kr/\n"
            "  - 키 없이 진행하려면: --from parse (계약 fixture 기반)",
            file=sys.stderr,
        )
        return 2

    init_schema(make_engine(settings))
    for stage in targets:
        print(f"[stage] {stage.value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 테스트 + CLI 동작 확인**

Run: `uv run pytest tests/test_pipeline.py -v && uv run python scripts/run_stage.py --only export`
Expected: PASS — 5 passed, 그리고 `[stage] export` 출력

- [ ] **Step 5: 전체 스위트 확인**

Run: `uv run pytest -v`
Expected: PASS — 전체 통과

- [ ] **Step 6: 커밋**

```bash
git add src/dartweave/pipeline.py scripts/run_stage.py tests/test_pipeline.py
git commit -m "feat: 파이프라인 단계 CLI (키 없으면 명확히 중단 + 우회 경로 안내)"
```

---

## 2. 위험 코드 지점

기술설계서 §6 의 위험 카테고리를 코드 위치에 매핑한다.

- `src/dartweave/dart/status.py:classify` — **breaking**: `013`(데이터 없음)을 실패로 분류하면 정상 기업이 수집 실패로 원장에 남아 대상 목록이 오염된다 | mitigation: `Action.EMPTY` 분리 + 미지 코드는 `ABORT` (Task 4 테스트가 고정)
- `src/dartweave/dart/client.py:get_json` — **side-effect**: `010`(잘못된 키)에 재시도를 걸면 무의미한 API 호출로 한도를 소진한다 | mitigation: `ABORT` 는 즉시 예외, 재시도 루프 진입 금지 (Task 5 `test_aborts_immediately_on_010_without_retry`)
- `src/dartweave/trust/mention.py:count_mentions` — **breaking**: 집계 키에서 보고 주체를 빼면 연차 반복이 자기 인용으로 가중치를 부풀린다 (AC-3 실패) | mitigation: 키를 `(reporter_corp_code, report_kind)` 로 고정 + `test_same_company_across_three_years_counts_as_one`
- `src/dartweave/trust/scope.py:compare_scope` — **breaking**: 스코프 비교를 빼면 정상적인 지분 매각이 전부 모순으로 튀어나와 1급의 권위가 무너진다 | mitigation: `Verdict.CHANGE` 분리 + 기준일 우선·사업연도 폴백
- `src/dartweave/trust/contradiction.py:detect_grade_a` — **side-effect**: 스코프를 무시하고 합산하면 정상 기업이 전부 위반으로 나온다. 허용치를 0으로 두면 반올림 오탐이 쏟아진다 | mitigation: `(대상, 스코프)` 버킷 + `SUM_TOLERANCE` + `share_pct is None` 은 0으로 치지 않음
- `src/dartweave/trust/weight.py:evidence_weight` — **breaking**: LLM 원본 `confidence` 를 산식에 직접 넣으면 AC-4c 위반 (미캘리브레이션 값이 가중치를 지배) | mitigation: `observed_precision` 우선, 미측정 시 보수적 상수 (`test_text_edge_uses_observed_precision_not_raw_confidence`)
- `src/dartweave/graph/load.py:build_edge_merge` — **side-effect**: `CREATE` 를 쓰거나 MERGE 키가 부실하면 재적재가 엣지를 중복 생성한다 | mitigation: 복합 MERGE 키 `(시작, 끝, 타입, fiscal_year, source, as_of)`
- `src/dartweave/graph/load.py:_require` — **breaking**: 미해소 대상에 노드를 자동 생성하면 그래프가 조용히 오염되고 교차확인이 실패한다 (AC-10) | mitigation: `ValueError` 로 차단, 신규 노드 생성 경로 자체를 두지 않음
- `src/dartweave/resolve/resolver.py:Resolver.resolve` — **breaking**: 해소 실패 시 코드를 날조하거나 이름을 그대로 키로 쓰면 같은 회사가 여러 노드로 쪼개져 교차확인이 실패하고 T1이 T2/T3로 강등된다 | mitigation: `corp_code=None` 반환 + 대기열 적재, `test_never_invents_a_corp_code`
- `src/dartweave/resolve/normalize.py:normalize_name` — **side-effect**: 접미사 제거를 과하게 하면 서로 다른 회사가 같은 키로 뭉친다 (예: 접미사 반복 제거 루프) | mitigation: 접미사 목록을 명시 리스트로 한정 + 정규화 테스트 고정. 오탐 발견 시 별칭 사전으로 보정
- `src/dartweave/db/ledger.py:upsert_disclosures` — **side-effect**: `fail_reason` 을 덮어쓰면 이전 실패 원인이 사라져 재개 판단이 불가능해진다 | mitigation: 멱등 테스트 + 상태·사유를 항상 함께 기록
- `scripts/run_stage.py:main` — **side-effect**: 키가 없는데 조용히 빈 결과로 진행하면 "수집 완료 0건" 이 성공처럼 보인다 | mitigation: exit code 2 + 우회 경로(`--from parse`) 명시 안내
- `docker-compose.yml` — **side-effect**: 호스트 포트가 `docs-rag`/`cogito`/`ga4` 스택과 겹치면 기동 실패 | mitigation: `tests/test_compose.py::test_ports_do_not_collide_with_existing_stack`
- `docker-compose.yml` (neo4j GPU 무관 / vLLM 미포함) — **side-effect**: 슬라이스 2에서 vLLM 추가 시 `docs-rag` vLLM 과 GPU 경합 | mitigation: 슬라이스 2 계획에서 순차 기동 명시. 슬라이스 1은 GPU 미사용

> ⚠️ **`race` 카테고리 없음** — 슬라이스 1은 수집이 단일 프로세스라는 전제다. 수집 병렬화를 도입하면 `disclosure` 원장 write 경합이 생기므로 그 시점에 본 절을 갱신해야 한다.

---

## 3. 롤백 전략

- **Code**: 태스크마다 원자 커밋이므로 `git revert <SHA>` 또는 `git reset --hard <직전 SHA>`. 슬라이스 전체 되돌리기는 `git reset --hard <Task 1 직전 SHA>`
- **Postgres**: 스키마는 `Base.metadata.create_all` 로만 만들며 파괴적 마이그레이션이 없다. 초기화는 `docker compose down -v` 후 재기동 (볼륨 `pg-data` 삭제)
- **Neo4j**: 제약·인덱스는 전부 `IF NOT EXISTS` 라 재실행 안전. 그래프 초기화는 `MATCH (n) DETACH DELETE n` 또는 볼륨 `neo4j-data` 삭제
- **적재 멱등성**: `MERGE` 복합 키 덕분에 재적재가 중복을 만들지 않으므로, 부분 실패 시 처음부터 다시 돌려도 안전하다
- **Config**: `.env` 만 되돌리면 되고 코드 변경 불필요 (모든 포트·경로가 `config.py` 경유)

---

## 변경이력

<!-- change-history skill auto-appends entries here, oldest first -->

### [2026-08-13 13:46] [구현계획서-수정]
- **id**: CH-20260813-006
- **이유**: 신규 구현 계획 (최초 생성). 층0 전체를 한 문서에 담으면 ~34 task 가 되어 읽지도 실행하지도 못하므로 **슬라이스 1(정형 전용)** 로 분할. 경계를 여기 둔 근거는 **정형↔정형 대조가 LLM 없이 성립**한다는 점 — 요구사항이 킬러로 꼽은 1급 모순(지분 합계 위반, 상호 지분율 불일치)이 추출 품질에 인질 잡히지 않고 먼저 나온다
- **무엇이**: `dual-source-trust-graph-implementation-plan.md` 전체 — frontmatter(`commit_policy: per-task`) / §1 단계별 작업 **23 task** / §2 위험 코드 지점 **14건** / §3 롤백 전략
- **자체 점검에서 발견·수정한 결함 3건**:
  - **경계 판단 오류** — 엔티티 해소를 슬라이스 2로 미뤘으나, 정형 API도 관계 상대를 이름 문자열로만 준다 (「최대주주 현황」 `nm`, 「타법인 출자현황」 `inv_prm` 에 `corp_code` 없음). LLM과 무관하게 정형만으로도 해소가 필요 → **Task 21 신설** + 슬라이스 경계 주석 명시
  - **조립 누락** — 초안 20 task 가 전부 순수 함수·생성기라 실제로 DB에 쓰는 코드가 0건이었음. 부품만 있고 실행 가능한 파이프라인이 아니었음 → **Task 22**(원장 멱등 upsert) · **Task 23**(단계 CLI + 키 부재 시 exit 2) 신설
  - **죽은 코드** — `build_edge_merge` 의 `if A or B: X else: X` 동일 분기 → 단일 경로로 정리
- **영향범위**: 없음 (최초 생성, 기존 코드 수정 0건). 슬라이스 2 계획서가 본 계획의 산출물(`RelationEdge` 스키마 · `Resolver` · `evidence_weight` 인자 구조 · 원장 테이블)을 입력으로 받는다
- **검증 결과**: `verifying-spec` 4축 — Mapped 8건(슬라이스 1 범위 AC 전량) / **Gaps 3건 (본 엔트리에서 해소)** / Conflicts 0건 / 위험 `breaking 6 · side-effect 8 · race 0` / 테스트 41파일 중 17개, **실 API·실 DB 없이 전 스위트 구동 가능**
  - ⚠️ `race 0` 은 수집이 단일 프로세스라는 전제. 병렬화 도입 시 `disclosure` write 경합을 §2에 추가해야 함
- **연관 항목**: CH-20260813-003, CH-20260813-004

### [2026-08-13 14:25] [구현계획서-수정]
- **id**: CH-20260813-007
- **이유**: 실행 중 발견된 **계획서 자체의 결함** 교정. Task 5 구현자가 `Status: BLOCKED` 로 에스컬레이션 — 같은 태스크의 테스트 블록과 구현 블록이 동시에 만족될 수 없었음. Task 20·23 구현자가 독립적으로 같은 실패를 재확인
- **무엇이**: Task 5 의 `test_empty_status_returns_empty_list_not_error` 단언
  - 전: `assert get_json(...) == {"status": "013", "list": []}` (전체 dict 동등)
  - 후: `status` · `list` · **`message` 보존**을 각각 단언
- **판정 근거**: 계획서 자신의 산문이 결정 — *"호출부가 분기하지 않도록 빈 list 를 채워 반환한다"*. 의도는 caller 가 `013` 을 특별취급하지 않게 하는 것이지 `message` 를 버리는 게 아니며, `message` 는 로그·디버깅에 필요하다. **구현이 옳고 테스트가 과도하게 엄격했음**
- **영향범위**: `tests/test_dart_client.py` 만. 구현 코드(`client.py`) 무변경
- **의의**: byte-copy 규율이 없었다면 구현자가 임의로 한쪽을 맞춰버렸을 것이고, 계획서와 코드가 조용히 갈라지는 지점이 됐을 것. 에스컬레이션이 정상 작동한 사례
- **연관 항목**: CH-20260813-006, CH-20260813-008

### [2026-08-13 14:25] [코드-수정] (batch: tasks 1..23)
- **id**: CH-20260813-008
- **이유**: 슬라이스 1(정형 전용) 전량 구현 완료. 정형 API만으로 신뢰 등급이 붙은 관계 그래프가 서고, **LLM 없이 1급 모순(정형↔정형 불일치)을 검출**하는 코드가 완성됨
- **무엇이**: `src/dartweave/` 전체 신규 (config · dart 5모듈 · parse 2모듈 · resolve 3모듈 · select 2모듈 · trust 6모듈 · graph 4모듈 · db 4모듈 · pipeline) + `scripts/run_stage.py` + `docker-compose.yml` + `pyproject.toml` + `tests/` 17파일
- **영향범위**: 신규 프로젝트 — 기존 코드 수정 0건. 슬라이스 2가 본 산출물(`RelationEdge` 스키마 · `Resolver` · `evidence_weight` 인자 구조 · 원장 9테이블)을 입력으로 받음
- **위험 카테고리**: `side-effect 10` · `breaking 3` · `race 1`
- **실행 방식**: subagent wave-parallel (5 waves) — implementer haiku byte-copy + spec reviewer sonnet 독립 검증. 전 태스크 리뷰어 ✅, 계획서 대비 byte-identity 를 `diff`/`cmp`/`md5sum` 으로 대조
- **task별 세부 (23건)**:
  - Wave 1 — Task 1 스캐폴딩: `aabdd45` (`side-effect`: `load_dotenv` 전역 env 변경)
  - Wave 2 — Task 2 `0158716`(`side-effect`: 평문 자격증명·호스트 포트 공개) / Task 3 `4dfa34e`(`breaking`: 마이그레이션 부재) / Task 4 `b3b2b3c` / Task 10 `ac36050` / Task 18 `cde3b9f` / Task 21 `4efb61b`(`side-effect`: 정규화 과도제거로 키 충돌)
  - Wave 3 — Task 5 `170a891`(`side-effect`: HTTP 클라이언트 수명·스로틀 비스레드안전) / Task 6 `3abcbba` / Task 7 `2fb9d0b` / Task 9 `c7e70df` / Task 11 `04fe079` / Task 13 `b5606e2`(`side-effect`: 판정 임계값) / Task 19 `4ccc41d`(`breaking`: MERGE 식별키 변경) / Task 20 `857353d` / Task 23 `c57ca13`(`side-effect`: import 실패가 안내 경로 우회)
  - Wave 4 — Task 8 `c4b3b86`(`side-effect`: 접두사 길이가 대상 규모 좌우) / Task 12 `e491774` / Task 14 `43c85a5`(`breaking`: 집계 키에 rcept_no 추가 금지) / Task 15 `fb78d27`(`side-effect`: 미해소가 SINGLE 로 위장) / Task 16 `7bf95ce` / Task 17 `9f64a18`(`side-effect`: 모순 허용치)
  - Wave 5 — Task 22 `177f0a7`(**`race`**: get-or-create TOCTOU · `side-effect`: `init_schema` DDL)
- **연관 commits**: `aabdd45..177f0a7` (23개)
- **변경 전/후 코드**: 생략 — `git show <SHA>` 로 조회
- **테스트**: **107 passed / 0 failed**. 실 API·실 DB 없이 전 스위트 구동 (httpx MockTransport + in-memory SQLite + 순수 함수)
- **연관 항목**: CH-20260813-006, CH-20260813-007

### [2026-08-13 14:25] [검증] (실행 전반)
- **id**: CH-20260813-009
- **이유**: subagent 실행의 계획 ↔ 실제 코드 갭 점검
- **무엇이**: 23개 태스크 × (implementer + spec reviewer) 독립 검증
- **결과**: **PASS** — 누락 0 · 초과 0 · blocked 0 · 코드변경 0건 task 0
  - 매니페스트 23/23 (DONE 22 · DONE_WITH_CONCERNS 1)
  - **DONE_WITH_CONCERNS 1건 = Task 23** — `scripts/run_stage.py` 가 `dartweave.db.session`(Task 22, 후행 wave)을 최상단 import 하여 CLI 스모크런 불가. Task 22 착지 후 재확인 결과 import 는 뚫렸으나 **Postgres 미기동으로 여전히 exit 1**
  - ⚠️ **미해결 (계획서 수준 갭, 구현자 이탈 아님)**: `run_stage.py` 가 요청 단계와 무관하게 `init_schema(make_engine(...))` 를 무조건 호출한다. DB 가 필요 없는 `export` 단계도 Postgres 없이는 raw traceback 으로 죽으며, 설계상 의도한 친절한 안내(exit 2)에 도달하지 못한다. Task 22 리뷰어가 계획서 Task 23 블록과 실행 로직이 byte-identical 임을 확인해 **계획서 설계 갭**으로 판정. 슬라이스 2에서 지연 import + 단계별 DB 필요 여부 판정으로 교정 예정
  - ⚠️ **`race 1` 신규**: 계획서 §2 는 "수집 단일 프로세스 전제로 race 0" 이었으나, 구현된 `ledger.py` 의 get-or-close 패턴이 실제 TOCTOU 지점임을 3-checklist 에서 확인. 병렬화 시 Postgres upsert 로 교체 필요 — 코드에 RISK 주석 기록
- **연관 commits**: `aabdd45..177f0a7`
- **연관 항목**: CH-20260813-008
