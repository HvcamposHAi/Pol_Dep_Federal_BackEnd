"""Rate limiter assíncrono por provider (intervalo mínimo entre chamadas).

Dorme apenas o tempo *restante* até o próximo slot, considerando a duração da
própria chamada anterior — mais preciso que um ``sleep`` fixo.
"""

from __future__ import annotations

import asyncio
import time


class AsyncRateLimiter:
    """Garante no mínimo ``min_interval`` segundos entre aquisições consecutivas."""

    def __init__(self, min_interval_seconds: float):
        self._min_interval = max(0.0, min_interval_seconds)
        self._lock = asyncio.Lock()
        self._next_allowed = 0.0

    @classmethod
    def from_rpm(cls, requests_per_minute: int) -> AsyncRateLimiter:
        rpm = max(1, requests_per_minute)
        return cls(60.0 / rpm)

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            wait = self._next_allowed - now
            if wait > 0:
                await asyncio.sleep(wait)
                now = time.monotonic()
            self._next_allowed = now + self._min_interval
