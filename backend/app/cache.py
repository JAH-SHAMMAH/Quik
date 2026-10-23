"""Short-lived offer cache.

Airline offers expire within minutes, so they live here rather than in the DB.
In-process for dev; replace with Redis (same get/set interface) when you run >1 worker.
"""
import time
from threading import Lock
from typing import Any


class TTLCache:
    def __init__(self, ttl_seconds: int = 30 * 60, max_items: int = 50_000):
        self.ttl, self.max = ttl_seconds, max_items
        self._data: dict[str, tuple[float, Any]] = {}
        self._lock = Lock()

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            if len(self._data) >= self.max:
                self._evict()
            self._data[key] = (time.monotonic() + self.ttl, value)

    def get(self, key: str) -> Any | None:
        with self._lock:
            item = self._data.get(key)
            if not item:
                return None
            exp, value = item
            if exp < time.monotonic():
                del self._data[key]
                return None
            return value

    def _evict(self) -> None:
        now = time.monotonic()
        for k in [k for k, (exp, _) in self._data.items() if exp < now]:
            del self._data[k]
        while len(self._data) >= self.max:
            self._data.pop(next(iter(self._data)))


offers = TTLCache()  # flight + hotel offers by id
searches = TTLCache()  # offer_id -> the FlightSearch that produced it
