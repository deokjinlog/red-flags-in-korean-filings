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


# 실데이터 반영: 「최대주주 현황」 응답은 개별 주주 행 사이에 소계/합계 행을 섞어 준다
# (nm="계", stock_knd 가 "보통주"/"기타"/"합계" 인 행). "계" 는 주주가 아니라 요약이므로
# 엣지로 만들면 지분 합계가 정확히 두 배가 되어 가짜 1급 모순이 생성된다.
# 실측: 티씨케이 50.4%+계 50.4%=100.8% / 삼성바이오로직스 74.35%×2=148.7%
_AGGREGATE_NAMES = frozenset({"계", "합계", "소계", "총계"})


def is_aggregate_row(item: dict[str, Any]) -> bool:
    """소계·합계 행인가. 이름에서 공백을 지우고 판정한다 (실데이터에 '김 형 관' 같은 표기가 있음)."""
    nm = str(item.get("nm", "")).replace(" ", "").strip()
    return nm in _AGGREGATE_NAMES


def parse_qty(raw: Any) -> int | None:
    """'298,818,100' 같은 주식수. 지분율과 달리 분모가 없어 신고서 간 직접 비교가 된다."""
    text = str(raw or "").strip().replace(",", "")
    if not text or text == "-":
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def normalize_as_of(raw: Any) -> str | None:
    text = str(raw or "").strip().replace("-", "").replace(".", "")
    return text if len(text) == 8 and text.isdigit() else None


def parse_major_shareholder(payload: dict[str, Any]) -> list[RelationEdge]:
    edges: list[RelationEdge] = []
    for item in payload.get("list", []):
        if is_aggregate_row(item):
            continue
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
                stock_knd=str(item.get("stock_knd", "")).strip() or None,
                share_qty=parse_qty(item.get("trmend_posesn_stock_co")),
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
                # 실데이터 확인: 응답 필드는 trmend_blce_qota_rt (기말잔액 지분율).
                # trmend_qota_rt 는 존재하지 않아 전건 None 이 되고 교차확인이 무력화됐다.
                share_pct=parse_ratio(item.get("trmend_blce_qota_rt")),
                share_qty=parse_qty(item.get("trmend_blce_qy")),
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
