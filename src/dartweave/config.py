"""환경 설정. 매직넘버는 전부 여기로 모은다."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# ⚠️ RISK(side-effect): import 시점에 os.environ 을 프로세스 전역으로 변경한다.
# .env 값이 임포트 순서에 따라 테스트/다른 모듈의 환경 읽기에 섞일 수 있다.
# 테스트는 monkeypatch 로 해당 키를 명시 삭제·설정해서 격리할 것. — by main(3-checklist: shared state)
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
