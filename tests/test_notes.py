"""주석 목차 — 읽어주지 않고 짚어준다."""
from dartweave.parse.notes import WORTH_READING, outline, worth_reading

BODY = """
<P>14. 유형자산</P><P>17. 담보제공자산 등</P><P>18. 차입금</P>
<P>23. 우발부채와 약정사항</P><P>35. 특수관계자</P>
<P>17. 담보제공자산 등</P>
<P>1. 개요</P>
"""


def test_outline_keeps_first_occurrence_only():
    """[기재정정] 보고서는 같은 제목이 정정 대비표에도 나온다 — 중복을 접는다."""
    got = outline(BODY)
    assert got.count(("17", "담보제공자산 등")) == 1
    assert ("23", "우발부채와 약정사항") in got


def test_worth_reading_attaches_the_reason():
    notes = {n.title: n for n in worth_reading(BODY)}
    assert notes["담보제공자산 등"].number == "17"
    assert "청산가치" in notes["담보제공자산 등"].why


def test_one_note_matches_one_keyword():
    """'우발부채와 약정사항' 이 두 키워드에 걸려 두 번 나오면 안 된다."""
    notes = worth_reading(BODY)
    titles = [n.title for n in notes]
    assert len(titles) == len(set(titles))


def test_short_or_missing_titles_are_dropped():
    assert not any(t == "개" for _, t in outline("<P>1. 개</P>"))
    assert worth_reading("") == []


def test_every_keyword_carries_a_reason():
    """이유 없이 '주석 17 보세요' 라고 하면 왜 보는지 모른다."""
    assert all(len(why) > 10 for _, why in WORTH_READING)


def test_one_note_number_appears_once():
    """실측 — '우발부채와 약정사항' 이 두 키워드에 걸려 같은 주석이 두 줄로 나왔다."""
    notes = worth_reading("<P>23. 우발부채와 약정사항</P><P>23. 우발부채와 약정사항 (연결)</P>")
    assert len(notes) == 1 and notes[0].number == "23"
