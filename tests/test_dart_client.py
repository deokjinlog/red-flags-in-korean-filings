import httpx
import pytest

from dartweave.dart.client import DartClient
from dartweave.dart.status import DartApiError


def _client(handler, **kw) -> DartClient:
    transport = httpx.MockTransport(handler)
    return DartClient(api_key="k" * 40, transport=transport, sleep=lambda _: None, **kw)


def test_get_json_returns_payload_on_000():
    def handler(request):
        return httpx.Response(200, json={"status": "000", "list": [{"a": 1}]})

    assert _client(handler).get_json("list.json", {})["list"] == [{"a": 1}]


def test_empty_status_returns_empty_list_not_error():
    def handler(request):
        return httpx.Response(200, json={"status": "013", "message": "no data"})

    payload = _client(handler).get_json("list.json", {})
    assert payload["status"] == "013"
    assert payload["list"] == []
    assert payload["message"] == "no data", "원본 메시지는 로그용으로 보존한다"


def test_retries_on_020_then_succeeds():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(200, json={"status": "020", "message": "limit"})
        return httpx.Response(200, json={"status": "000", "list": []})

    assert _client(handler, max_retries=5).get_json("list.json", {})["status"] == "000"
    assert calls["n"] == 3


def test_aborts_immediately_on_010_without_retry():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(200, json={"status": "010", "message": "bad key"})

    with pytest.raises(DartApiError) as ei:
        _client(handler, max_retries=5).get_json("list.json", {})
    assert ei.value.status == "010"
    assert calls["n"] == 1, "잘못된 키는 재시도하면 안 됨"


def test_api_key_is_injected_into_every_request():
    seen = {}

    def handler(request):
        seen.update(dict(request.url.params))
        return httpx.Response(200, json={"status": "000"})

    _client(handler).get_json("list.json", {"corp_code": "00126380"})
    assert seen["crtfc_key"] == "k" * 40
    assert seen["corp_code"] == "00126380"
