"""Method 6: application-level cached search.

The cache is an in-memory TTL + LRU cache, not a database index. A cache miss
runs the hybrid search (including query embedding and PostgreSQL execution); a
cache hit returns the stored result without touching PostgreSQL.
"""
from __future__ import annotations

import copy
import time
from datetime import datetime, timezone

import numpy as np

from ..cache import cache
from ..embeddings import encode_query
from ..query_parser import ParsedQuery
from . import hybrid

METHOD = "cached"
LABEL = "Cached Search"
DESCRIPTION = (
    "Application-level TTL/LRU cache in front of hybrid search. The first "
    "query is a miss; repeated identical queries are hits that skip both "
    "embedding generation and database execution."
)
EXPECTED_INDEX = "no database index (application cache)"


def search(
    parsed: ParsedQuery,
    limit: int,
    include_plan: bool = True,
    query_embedding: np.ndarray | None = None,
) -> dict:
    key = cache.make_key(parsed.normalized_query, limit, METHOD)
    lookup_started = time.perf_counter()
    cached_value, cache_meta = cache.get(key)
    lookup_ms = (time.perf_counter() - lookup_started) * 1000

    if cached_value is not None:
        result = copy.deepcopy(cached_value)
        result["db_execution_ms"] = 0.0
        result["plan_capture_ms"] = 0.0
        result["cache"] = {
            **cache_meta,
            "key": key,
            "lookup_ms": round(lookup_ms, 4),
            "ttl_seconds": cache.ttl_seconds,
            "stats": cache.stats(),
        }
        result["embedding_ms"] = 0.0
        result["method_details"] = {
            **result.get("method_details", {}),
            "cache_hit": True,
            "cache_layer": "in-memory TTL/LRU",
            "underlying_method": "hybrid",
            "original_db_execution_ms": cached_value.get("db_execution_ms"),
            "note": (
                "Cache hit: no embedding generation and no PostgreSQL query were "
                "performed. The returned rows and technical plan were produced by "
                "the original cache-miss execution."
            ),
        }
        result["cached_plan"] = result.get("plan") is not None
        return result

    embedding_ms = 0.0
    if query_embedding is None:
        query_embedding, embedding_ms = encode_query(parsed.original_query)

    started = time.perf_counter()
    outcome = hybrid.search(
        parsed, limit, include_plan=include_plan, query_embedding=query_embedding
    )
    miss_search_ms = (time.perf_counter() - started) * 1000
    outcome["embedding_ms"] = round(embedding_ms, 3)

    stored = copy.deepcopy(outcome)
    stored["cached_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    cache.set(key, stored)

    outcome["cache"] = {
        **cache_meta,
        "key": key,
        "lookup_ms": round(lookup_ms, 4),
        "miss_search_ms": round(miss_search_ms, 3),
        "ttl_seconds": cache.ttl_seconds,
        "stats": cache.stats(),
    }
    outcome["method_details"] = {
        **outcome.get("method_details", {}),
        "cache_hit": False,
        "cache_layer": "in-memory TTL/LRU",
        "underlying_method": "hybrid",
        "note": (
            "Cache miss: hybrid search was executed and the result was stored. "
            "Repeating the same query and limit should produce a cache hit."
        ),
    }
    return outcome
