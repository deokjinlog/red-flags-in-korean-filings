import pytest

from dartweave.pipeline import STAGES, Stage, resolve_stage, stages_from


def test_stage_order_is_fixed():
    assert [s.value for s in STAGES] == [
        "select",
        "collect",
        "parse",
        "resolve",
        "load",
        "trust",
        "export",
    ]


def test_resolve_stage_accepts_name():
    assert resolve_stage("load") is Stage.LOAD


def test_unknown_stage_raises_with_available_list():
    with pytest.raises(ValueError) as ei:
        resolve_stage("nope")
    assert "select" in str(ei.value)


def test_stages_from_returns_suffix():
    assert stages_from(Stage.LOAD) == [Stage.LOAD, Stage.TRUST, Stage.EXPORT]


def test_stages_from_first_returns_all():
    assert stages_from(Stage.SELECT) == list(STAGES)
