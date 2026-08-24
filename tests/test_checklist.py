"""종목 체크리스트 — 판정 대신 위치."""
from dartweave.screen.checklist import NOT_CHECKED, build, evidence_of
from dartweave.screen.flags import ADOPTED_KINDS, Flag


def _f(kind, summary="요약", evidence=None):
    return Flag(kind=kind, summary=summary, evidence=evidence or ["근거"])


def test_splits_fired_clear_and_unknown():
    """'0개 걸림' 이 안전을 뜻하는지 알려면 안 걸린 것과 못 잰 것을 갈라야 한다."""
    known = {k: False for k in ADOPTED_KINDS}
    known["결손금"] = True
    known["영업현금흐름 음수"] = None
    c = build("A사", "0001", "2024", [_f("결손금")], known)
    assert [f.kind for f in c.fired] == ["결손금"]
    assert "영업현금흐름 음수" in c.unknown
    assert "영업손실" in c.clear
    assert len(c.fired) + len(c.clear) + len(c.unknown) == len(ADOPTED_KINDS)


def test_unverified_flags_go_to_reference_not_fired():
    """검정 미통과 신호를 걸린 것에 섞으면 개수가 뜻을 잃는다."""
    c = build("A사", "0001", "2024",
              [_f("결손금"), _f("공동의존점 근접")], {k: False for k in ADOPTED_KINDS})
    assert [f.kind for f in c.fired] == ["결손금"]
    assert [f.kind for f in c.reference] == ["공동의존점 근접"]


def test_summary_says_when_something_could_not_be_judged():
    known = {k: False for k in ADOPTED_KINDS}
    known["결손금"] = None
    c = build("A사", "0001", "2024", [], known)
    assert "판정 못 함" in c.summary


def test_evidence_splits_verdict_line():
    f = _f("결손금", evidence=["실측 부실률 6.7~9.6%", "└ **채택** · 4시점 전부"])
    lines, verdict = evidence_of(f)
    assert lines == ["실측 부실률 6.7~9.6%"]
    assert verdict.startswith("**채택**")


def test_not_checked_list_names_what_we_cannot_read():
    """이걸 안 적으면 '체크리스트를 통과했으니 괜찮다' 로 읽힌다."""
    topics = {t for t, _ in NOT_CHECKED}
    assert "주석 · 우발부채" in topics and "담보 제공 자산" in topics
    assert "계정 사이의 연결" in topics
