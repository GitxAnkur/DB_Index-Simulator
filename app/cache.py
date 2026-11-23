"""Thread-safe in-memory TTL + LRU cache for search results.

The cache is an application-level optimisation, not a database index. Cache
hits bypass both embedding generation and PostgreSQL execution.
"""
from __future__ import annotations

import hashlib
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any


@dataclass
class CacheEntry:
    value: Any
    created_at: float
    expires_at: float
    hits: int = 0


class TTLCache:
    def __init__(self, max_entries: int = 512, ttl_seconds: int = 300) -> None:
        self.max_entries = max_entries
        self.ttl_seconds = ttl_seconds
        self._data: OrderedDict[str, CacheEntry] = OrderedDict()
        self._lock = threading.RLock()
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._expirations = 0

    @staticmethod
    def make_key(query: str, limit: int, method: str) -> str:
        raw = f"{method}|{query.strip().lower()}|{limit}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

    def get(self, key: str) -> tuple[Any | None, dict[str, Any]]:
        now = time.monotonic()
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                self._misses += 1
                return None, {"status": "miss", "reason": "not_found"}
            if entry.expires_at <= now:
                del self._data[key]
                self._expirations += 1
                self._misses += 1
                return None, {"status": "miss", "reason": "expired"}
            entry.hits += 1
            self._data.move_to_end(key)
            self._hits += 1
            return entry.value, {
                "status": "hit",
                "age_seconds": round(now - entry.created_at, 3),
                "ttl_remaining_seconds": round(entry.expires_at - now, 3),
                "entry_hits": entry.hits,
            }

    def set(self, key: str, value: Any) -> dict[str, Any]:
        now = time.monotonic()
        with self._lock:
            self._data[key] = CacheEntry(
                value=value,
                created_at=now,
                expires_at=now + self.ttl_seconds,
            )
            self._data.move_to_end(key)
            while len(self._data) > self.max_entries:
                self._data.popitem(last=False)
                self._evictions += 1
            return {
                "status": "stored",
                "ttl_seconds": self.ttl_seconds,
                "entries": len(self._data),
            }

    def delete(self, key: str) -> bool:
        with self._lock:
            return self._data.pop(key, None) is not None

    def invalidate_prefix(self, prefix: str) -> int:
        with self._lock:
            keys = [k for k in self._data if k.startswith(prefix)]
            for key in keys:
                del self._data[key]
            return len(keys)

    def clear(self) -> int:
        with self._lock:
            count = len(self._data)
            self._data.clear()
            return count

    def stats(self) -> dict[str, Any]:
        with self._lock:
            total = self._hits + self._misses
            return {
                "entries": len(self._data),
                "max_entries": self.max_entries,
                "ttl_seconds": self.ttl_seconds,
                "hits": self._hits,
                "misses": self._misses,
                "evictions": self._evictions,
                "expirations": self._expirations,
                "hit_rate": round(self._hits / total, 4) if total else 0.0,
            }

    def reset_stats(self) -> None:
        with self._lock:
            self._hits = 0
            self._misses = 0
            self._evictions = 0
            self._expirations = 0


cache = TTLCache()


def configure_cache(max_entries: int, ttl_seconds: int) -> None:
    cache.max_entries = max_entries
    cache.ttl_seconds = ttl_seconds
