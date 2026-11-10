"""In-process operational metrics (F14): ingestion rate, latency, queue depth,
detection run time. Shown on the dashboard Overview and /api/v1/stats/metrics."""

import time
from collections import deque
from dataclasses import dataclass, field


@dataclass
class Metrics:
    started_at: float = field(default_factory=time.time)
    ingested: int = 0
    errors: int = 0
    queue_depth: int = 0
    latencies_ms: deque = field(default_factory=lambda: deque(maxlen=1000))
    ingest_times: deque = field(default_factory=lambda: deque(maxlen=5000))
    last_detection: dict | None = None
    last_propagation: dict | None = None

    def record_ingest(self, latency_ms: float) -> None:
        self.ingested += 1
        self.latencies_ms.append(latency_ms)
        self.ingest_times.append(time.time())

    def snapshot(self) -> dict:
        now = time.time()
        latencies = sorted(self.latencies_ms)

        def pct(p: float) -> float | None:
            return latencies[min(len(latencies) - 1, int(p * len(latencies)))] if latencies else None

        return {
            "uptime_s": round(now - self.started_at),
            "ingested_total": self.ingested,
            "errors": self.errors,
            "queue_depth": self.queue_depth,
            "ingest_rate_per_min": sum(1 for t in self.ingest_times if now - t <= 60),
            "latency_ms_p50": pct(0.5),
            "latency_ms_p95": pct(0.95),
            "last_detection": self.last_detection,
            "last_propagation": {k: v for k, v in (self.last_propagation or {}).items() if k != "pre_emptive"}
            or None,
        }
