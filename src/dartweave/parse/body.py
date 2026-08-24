"""공시 원문 파싱 — DART 가 셀에 붙여둔 코드를 읽는다.

왜 LLM 이 아닌가:
  원문을 보기 전에는 "본문 추출 = LLM" 이라고 생각했다. 실제로 열어보니 DART 원문의
  표 셀에는 **의미 코드가 붙어 있다**:

      <TE ACODE="INV_PRM">㈜금강레저</TE>
      <TE ACODE="INV_LPR">20.50</TE>

  `INV_PRM` 은 법인명, `INV_LPR` 은 기말 지분율이다. 열 위치나 헤더 문구를 추측할
  필요가 없고, 제출사마다 표가 달라도 코드는 같다. **LLM 을 쓸 자리가 아니다** —
  쓰면 결정적으로 풀 수 있는 걸 확률적으로 푸는 것이고, 검증 비용만 늘어난다.

  본문에서 정말 LLM 이 필요한 건 코드가 안 붙은 서술 문단 쪽이다. 그건 이 모듈이
  아니라 별도 계층이고, **여기서 잰 재현율이 그 계층의 상한선**이 된다.

정형 API 와 겹치는 것부터 재는 이유:
  본문 추출이 얼마나 믿을 만한지 알려면 정답이 있어야 한다. 타법인 출자현황은
  정형 API(`otrCprInvstmntSttus`)에도 있으니, 같은 문서에서 뽑아 대조하면 사람이
  라벨을 달지 않고도 재현율·정밀도가 나온다. 재기 전에는 쓰지 않는다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# <TE ACODE="INV_PRM" ...>값</TE> / <TU AUNIT="INV_YN" ...>값</TU>
_CELL = re.compile(
    r"<T[EUD][^>]*?(?:ACODE|AUNIT)=\"([A-Z_0-9]+)\"[^>]*>(.*?)</T[EUD]>",
    re.S | re.I,
)
_ROW = re.compile(r"<TR[^>]*>(.*?)</TR>", re.S | re.I)
_TAG = re.compile(r"<[^>]+>")


def _text(raw: str) -> str:
    return re.sub(r"\s+", " ", _TAG.sub("", raw)).strip()


def coded_rows(xml: str) -> list[dict[str, str]]:
    """행마다 {코드: 값} 으로 돌려준다. 코드가 하나도 없는 행은 버린다."""
    out: list[dict[str, str]] = []
    for row in _ROW.findall(xml):
        cells = {code: _text(value) for code, value in _CELL.findall(row)}
        cells = {k: v for k, v in cells.items() if v and v != "-"}
        if cells:
            out.append(cells)
    return out


@dataclass(frozen=True)
class BodyInvestment:
    name: str
    share_pct: float | None


def _pct(raw: str | None) -> float | None:
    if not raw:
        return None
    cleaned = re.sub(r"[^\d.\-]", "", raw)
    try:
        value = float(cleaned)
    except ValueError:
        return None
    # 지분율이 100 을 넘으면 그 칸은 지분율이 아니다(수량·금액이 섞여 들어온 것).
    return value if 0.0 <= value <= 100.0 else None


def extract_investments(xml: str) -> list[BodyInvestment]:
    """타법인 출자현황 — 법인명과 **기말** 지분율.

    기초(`INV_BPR`)가 아니라 기말(`INV_LPR`)을 쓴다. 정형 API 가 보고서 기준일의
    보유를 주므로 기초를 쓰면 한 해 어긋난 값끼리 대조하게 된다.
    """
    seen: dict[str, BodyInvestment] = {}
    for row in coded_rows(xml):
        name = row.get("INV_PRM")
        if not name:
            continue
        pct = _pct(row.get("INV_LPR"))
        # 같은 법인이 여러 번 나오면 지분율이 있는 쪽을 남긴다.
        if name not in seen or (seen[name].share_pct is None and pct is not None):
            seen[name] = BodyInvestment(name=name, share_pct=pct)
    return list(seen.values())
