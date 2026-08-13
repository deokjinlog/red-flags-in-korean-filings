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
        # ⚠️ RISK(side-effect): 접두사 길이가 곧 대상 규모를 정한다. "261" 대신 "26" 이나 "2" 를 주면
        # 매칭 기업이 수십~수백 배로 폭증해 수집·추출 비용이 통째로 달라진다(API 한도까지 소진).
        # 접두사 변경 시 select 단계를 dry-run 해서 건수를 먼저 확인할 것.
        # — by main(3-checklist: 입력 하나가 하류 전체 규모를 좌우)
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
