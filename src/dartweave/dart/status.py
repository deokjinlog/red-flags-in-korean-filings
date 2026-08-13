"""DART OpenAPI 상태코드 분기. 모든 응답이 이 한 지점을 통과한다."""
from __future__ import annotations

from enum import Enum


class Action(Enum):
    OK = "ok"
    EMPTY = "empty"
    RETRY = "retry"
    ABORT = "abort"


class DartApiError(RuntimeError):
    def __init__(self, status: str, message: str) -> None:
        self.status = status
        self.message = message
        super().__init__(f"[{status}] {message}")


_MAP = {
    "000": Action.OK,
    "013": Action.EMPTY,
    "020": Action.RETRY,
}


def classify(status: str) -> Action:
    """알 수 없는 코드는 조용히 넘기지 않고 ABORT 한다."""
    return _MAP.get(status, Action.ABORT)
