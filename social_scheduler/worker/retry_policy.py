from __future__ import annotations

from datetime import timedelta

RETRY_DELAYS = [timedelta(minutes=5), timedelta(minutes=15), timedelta(minutes=45)]


def retry_delay(attempt_number: int) -> timedelta | None:
    idx = attempt_number - 1
    if idx < 0 or idx >= len(RETRY_DELAYS):
        return None
    return RETRY_DELAYS[idx]
