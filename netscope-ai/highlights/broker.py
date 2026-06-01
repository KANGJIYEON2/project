"""In-memory event broker for Server-Sent Events (single-process dev stack).

The ingest hot path is synchronous (runs in a threadpool); the SSE endpoint is
an async generator. Rather than bridge threads with a loop, we keep a small
thread-safe ring buffer of recent events. Each SSE subscriber tracks the last
event id it has seen and pulls newer ones for its tenant on a short interval.

NOTE: in-memory => correct only for a single uvicorn process. For multi-worker /
multi-instance deployments, swap this for Redis pub/sub or Postgres LISTEN/NOTIFY.
"""
from __future__ import annotations

import itertools
import threading
from collections import deque


class EventBroker:
    def __init__(self, maxlen: int = 1000):
        self._events: deque[tuple[int, dict]] = deque(maxlen=maxlen)
        self._lock = threading.Lock()
        self._counter = itertools.count(1)

    def publish(self, event: dict) -> int:
        """Append an event; returns its monotonic id."""
        with self._lock:
            eid = next(self._counter)
            self._events.append((eid, event))
            return eid

    def latest_id(self) -> int:
        with self._lock:
            return self._events[-1][0] if self._events else 0

    def since(self, last_id: int, tenant_id: str) -> list[tuple[int, dict]]:
        """Events newer than last_id that belong to the given tenant."""
        with self._lock:
            return [
                (eid, e)
                for (eid, e) in self._events
                if eid > last_id and e.get("tenant_id") == tenant_id
            ]


broker = EventBroker()
