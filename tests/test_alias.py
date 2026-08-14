"""별칭 사전 — 표기 차이로만 안 붙는 법인을 손으로 이어준다.

실측(표본 15사)에서 분류 교정 뒤 남은 미해소 법인은 24종이었고, 그중 자동 매칭
후보가 5건 나왔는데 **1건이 오탐**이었다. `부산조선해양기자재공업협동조합`(선박기자재
조합)이 접두 일치로 `부산조선`(별개 회사)에 붙었다. 그래서 이 사전은 자동 생성물이
아니라 **검증한 것만 손으로 넣는다.**
"""
import pytest

from dartweave.resolve.aliases import SEED_ALIASES, load_aliases
from dartweave.resolve.normalize import normalize_name
from dartweave.resolve.resolver import Resolver


def test_seed_keys_are_normalized():
    """정규화된 키로 저장해야 조회 때 맞는다 — Resolver 가 normalize 후 조회한다."""
    for k in SEED_ALIASES:
        assert k == normalize_name(k), k


def test_corp_codes_are_eight_digits():
    for k, v in SEED_ALIASES.items():
        assert len(v) == 8 and v.isdigit(), (k, v)


def test_full_legal_name_resolves_to_its_short_registry_name():
    """corpCode 는 약칭 '삼성생명' 으로 갖고 있고 공시는 정식명 '삼성생명보험㈜' 을 쓴다."""
    r = Resolver(official={}, aliases=load_aliases())
    assert r.resolve("삼성생명보험㈜", rcept_no="x").corp_code == "00126256"


def test_footnote_marker_is_bridged():
    """'(*1)' 은 표 각주 기호지 상호의 일부가 아니다."""
    r = Resolver(official={}, aliases=load_aliases())
    assert r.resolve("삼성벤처투자(*1)", rcept_no="x").corp_code == "00301574"


def test_former_name_annotation_is_bridged():
    r = Resolver(official={}, aliases=load_aliases())
    got = r.resolve("(주)삼성글로벌리서치 (구, 삼성경제연구소)(*1)", rcept_no="x")
    assert got.corp_code == "00217798"


def test_prefix_lookalike_is_not_in_the_seed():
    """오탐 회귀 방지.

    `부산조선해양기자재공업협동조합` 은 `부산조선` 과 **다른 법인**이다. 접두가 겹친다는
    이유로 넣으면 서로 다른 두 회사가 한 노드로 합쳐지고, 그 오염은 군집까지 흘러간다.
    """
    assert normalize_name("부산조선해양기자재공업협동조합") not in SEED_ALIASES


def test_official_registry_wins_over_alias():
    """사전은 보정 수단이지 우회로가 아니다 — 정식 등재가 있으면 그쪽이 이긴다."""
    r = Resolver(official={"삼성생명보험": "99999999"}, aliases=load_aliases())
    assert r.resolve("삼성생명보험㈜", rcept_no="x").corp_code == "99999999"


def test_unknown_name_still_unresolved():
    r = Resolver(official={}, aliases=load_aliases())
    assert r.resolve("듣보잡홀딩스주식회사", rcept_no="x").corp_code is None


@pytest.mark.parametrize("surface", list(SEED_ALIASES))
def test_every_seed_entry_actually_resolves(surface):
    """사전에 넣어놓고 조회가 안 되면 넣으나 마나다."""
    r = Resolver(official={}, aliases=load_aliases())
    assert r.resolve(surface, rcept_no="x").corp_code == SEED_ALIASES[surface]
