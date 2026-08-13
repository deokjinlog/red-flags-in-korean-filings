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
