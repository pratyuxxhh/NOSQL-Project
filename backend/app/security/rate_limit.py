"""Rate limiting.

- Login (per client IP) uses slowapi.
- Ingestion (per API key) uses a sliding one-minute window, because each key
  carries its own limit set by the admin.
"""

import time
from collections import defaultdict, deque

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)


class SlidingWindow:
    def __init__(self, window_s: float = 60.0) -> None:
        self.window_s = window_s
        self.hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str, limit: int, cost: int = 1) -> bool:
        now = time.monotonic()
        hits = self.hits[key]
        while hits and now - hits[0] > self.window_s:
            hits.popleft()
        if len(hits) + cost > limit:
            return False
        hits.extend([now] * cost)
        return True


ingest_window = SlidingWindow()
