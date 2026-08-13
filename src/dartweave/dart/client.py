"""DART OpenAPI 클라이언트. 상태코드 분기는 status.classify 한 지점에서만 한다."""
from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import httpx

from dartweave.config import DART_BASE_URL
from dartweave.dart.status import Action, DartApiError, classify


class DartClient:
    def __init__(
        self,
        api_key: str,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        max_retries: int = 3,
        backoff_base: float = 2.0,
        min_interval: float = 0.0,
    ) -> None:
        self._key = api_key
        self._sleep = sleep
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._min_interval = min_interval
        self._last_call = 0.0
        # ⚠️ RISK(side-effect): httpx.Client 를 생성만 하고 컨텍스트 매니저로 감싸지 않는다.
        # 호출부가 close() 를 안 부르면 소켓이 남는다. 대량 수집에서 인스턴스를 반복 생성하면
        # 파일 디스크립터가 고갈될 수 있으니, 수집 러너는 클라이언트 1개를 재사용하고 끝에 close() 할 것.
        # 또한 _last_call 기반 스로틀은 스레드 안전하지 않다 — 수집 병렬화 시 락이 필요하다.
        # — by main(3-checklist: shared state / 자원 수명)
        self._http = httpx.Client(
            base_url=DART_BASE_URL, transport=transport, timeout=30.0
        )

    def _throttle(self) -> None:
        if self._min_interval <= 0:
            return
        gap = time.monotonic() - self._last_call
        if gap < self._min_interval:
            self._sleep(self._min_interval - gap)
        self._last_call = time.monotonic()

    def get_json(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        merged = {**params, "crtfc_key": self._key}
        for attempt in range(self._max_retries + 1):
            self._throttle()
            resp = self._http.get(path, params=merged)
            resp.raise_for_status()
            payload = resp.json()
            action = classify(str(payload.get("status", "")))

            if action is Action.OK:
                return payload
            if action is Action.EMPTY:
                # 데이터 없음은 정상. 호출부가 분기하지 않도록 빈 list 를 채워 반환한다.
                return {**payload, "list": []}
            if action is Action.ABORT:
                raise DartApiError(
                    str(payload.get("status")), str(payload.get("message", ""))
                )
            if attempt < self._max_retries:
                self._sleep(self._backoff_base**attempt)

        raise DartApiError("020", f"{self._max_retries}회 재시도 후에도 한도 초과")

    def get_bytes(self, path: str, params: dict[str, Any]) -> bytes:
        """ZIP 응답용 (corpCode.xml, document.xml)."""
        self._throttle()
        resp = self._http.get(path, params={**params, "crtfc_key": self._key})
        resp.raise_for_status()
        return resp.content

    def close(self) -> None:
        self._http.close()
