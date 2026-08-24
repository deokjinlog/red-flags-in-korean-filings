"""주석 목차 — 사람이 읽을 자리를 짚어준다.

왜 추출이 아니라 목차인가:
  타법인 출자현황은 셀에 `ACODE` 가 붙어 있어 결정적으로 뽑았고, 정형 API 를 정답으로
  두고 재현율 100% 를 쟀다. **주석은 둘 다 없다.**

  1. 코드가 없다 — 지급보증 표 34개 중 코드가 붙은 건 1개, 담보 12개 중 0개다.
     정형 서식이 아니라 자유 서술이라 그렇다.
  2. 표가 전치되고 다층이다 — 행이 항목, 열이 상대방·권리 종류이고 열 개수가
     표마다 다르다. 열 위치로는 못 읽는다.
  3. **정답지가 없다.** 지급보증 총액을 대조할 정형 데이터가 어디에도 없다.
     추출 품질을 못 재고, 우리 규율은 "재기 전에는 안 쓴다" 다.

  그래서 여기서는 **읽어주지 않는다.** 대신 주석이 번호·제목으로 구조화돼 있으니
  "이 회사는 주석 17·23·35 를 보라" 까지를 정확히 짚어준다. 그게 이 단계에서
  정직하게 줄 수 있는 값이다 — 7백만 자에서 세 곳을 찾아주는 것.

⚠️ [기재정정] 보고서는 앞에 정정 대비표가 깔려 있어 키워드가 거기서 먼저 걸린다.
   목차만 뽑고 본문 위치는 **마지막 등장**으로 잡는다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# 주석 제목 → 왜 봐야 하는가. 붙여준 수기 리포트가 값어치 있게 읽은 자리들이다.
WORTH_READING: tuple[tuple[str, str], ...] = (
    ("담보제공자산", "자산이 죄다 담보면 청산가치가 없다. 채권최고액 대비 여력을 본다"),
    ("우발부채", "지급보증·계류 중 소송 — 숫자표에 안 나오는 부외부채"),
    ("약정사항", "한도대출·풋옵션 같은 조건부 의무"),
    ("특수관계자", "대여금·자금거래·일감몰아주기. 오너가 회사 돈을 빼가는 통로"),
    ("차입금", "만기 구조. 1년 안에 갚을 게 현금보다 많은가"),
    ("무형자산", "개발비 자산화액. 손상되면 자본이 그만큼 준다"),
    ("종속기업", "숨은 부실 자회사. 투자 손상 여부"),
)

_HEAD = re.compile(r">\s*(\d{1,2})\.\s*([가-힣A-Za-z·()\s]{2,30}?)\s*<")


@dataclass(frozen=True)
class Note:
    number: str
    title: str
    why: str


def outline(xml: str) -> list[tuple[str, str]]:
    """원문에서 `N. 제목` 형태의 주석 목차를 뽑는다. 중복은 앞선 것만 남긴다."""
    seen: list[tuple[str, str]] = []
    keys: set[tuple[str, str]] = set()
    for number, raw in _HEAD.findall(xml):
        title = re.sub(r"\s+", " ", raw).strip()
        if len(title) < 2:
            continue
        key = (number, title)
        if key not in keys:
            keys.add(key)
            seen.append(key)
    return seen


def worth_reading(xml: str) -> list[Note]:
    """읽을 값이 있는 주석만 골라 번호와 이유를 붙인다.

    같은 제목이 여러 번호로 나오면(연결·별도) 첫 번호만 쓴다 — 사람이 그 근처를
    보면 나머지도 보인다.

    ⚠️ **한 주석이 두 키워드에 걸리는 경우가 있다.** "우발부채와 약정사항" 이
    `우발부채` 와 `약정사항` 양쪽에 맞아서 같은 주석이 두 줄로 나왔다. 번호 기준으로도
    한 번만 담는다.
    """
    found: list[Note] = []
    taken: set[str] = set()
    used_numbers: set[str] = set()
    for number, title in outline(xml):
        if number in used_numbers:
            continue
        for keyword, why in WORTH_READING:
            if keyword in title and keyword not in taken:
                taken.add(keyword)
                used_numbers.add(number)
                found.append(Note(number=number, title=title, why=why))
                break
    return found
