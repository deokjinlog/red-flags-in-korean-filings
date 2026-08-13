import pytest

from dartweave.dart.status import Action, DartApiError, classify


def test_000_is_ok():
    assert classify("000") is Action.OK


def test_013_is_empty_not_failure():
    """데이터 없음은 정상. 실패로 처리하면 원장이 오염된다."""
    assert classify("013") is Action.EMPTY


def test_020_is_retryable():
    assert classify("020") is Action.RETRY


def test_010_aborts_immediately():
    """잘못된 키는 재시도해도 소용없다. 즉시 중단."""
    assert classify("010") is Action.ABORT


@pytest.mark.parametrize("code", ["011", "012", "100", "800", "900", "901"])
def test_unknown_codes_are_fatal_not_silently_ok(code):
    assert classify(code) is Action.ABORT


def test_dart_api_error_carries_code():
    err = DartApiError("010", "등록되지 않은 키입니다")
    assert err.status == "010"
    assert "010" in str(err)
