"""원장 멱등 upsert. 재실행이 중복을 만들지 않아야 재개가 성립한다."""
from __future__ import annotations

from sqlalchemy.orm import Session

from dartweave.dart.disclosure import DisclosureRow
from dartweave.db.models import Company, Disclosure
from dartweave.select.targets import SelectedCompany


def upsert_companies(session: Session, picked: list[SelectedCompany]) -> int:
    # ⚠️ RISK(race): get-or-create 는 조회와 삽입 사이가 원자적이지 않다. 지금은 수집이
    # 단일 프로세스라 안전하지만(계획서 §2 의 "race 0" 전제가 바로 이 지점), 병렬화하면
    # 두 워커가 같은 corp_code 를 동시에 없다고 판단해 중복 INSERT → PK 충돌로 터진다.
    # 병렬화 시 INSERT ... ON CONFLICT DO UPDATE (Postgres upsert) 로 교체할 것.
    # 같은 지적이 upsert_disclosures 에도 그대로 적용된다.
    # — by main(3-checklist: TOCTOU)
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
