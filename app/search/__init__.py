"""Search dispatcher: validates the selected method and assembles the API
response. Six methods remain separately selectable and separately measured.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

import numpy as np

from ..config import Config
from ..embeddings import encode_query
from ..query_parser import ParsedQuery, keywords_match_exists, parse_query
from . import cached, composite_btree, full_scan, hash_index, hnsw, hybrid

METHOD_MODULES = {
    "full_scan": full_scan,
    "hash": hash_index,
    "composite_btree": composite_btree,
    "hnsw": hnsw,
    "hybrid": hybrid,
    "cached": cached,
}

METHOD_ORDER = [
    "full_scan",
    "hash",
    "composite_btree",
    "hnsw",
    "hybrid",
    "cached",
]

COMPARABILITY = {
    "full_scan": {
        "comparable": True,
        "group": "relational",
        "note": "Same parsed filters and keyword predicate as the other relational methods; index scans are disabled by design.",
    },
    "hash": {
        "comparable": True,
        "group": "relational",
        "note": "Same query as the relational baseline; the hash index applies only when a brand equality predicate exists.",
    },
    "composite_btree": {
        "comparable": True,
        "group": "relational",
        "note": "Same query as the relational baseline; the composite index applies when category is constrained.",
    },
    "hnsw": {
        "comparable": False,
        "group": "semantic",
        "note": "Returns approximate semantic nearest neighbours without structured filters. Result semantics differ from relational methods; query embedding time is reported separately.",
    },
    "hybrid": {
        "comparable": False,
        "group": "semantic",
        "note": "Uses structured filters plus semantic ranking. Result ordering differs from relational methods; embedding time is reported separately.",
    },
    "cached": {
        "comparable": False,
        "group": "cache",
        "note": "Timing depends on cache state: the first run is a miss, later runs are hits. Cache hits avoid the database entirely.",
    },
}


def methods_info() -> list[dict[str, Any]]:
    info = []
    for method_id in METHOD_ORDER:
        module = METHOD_MODULES[method_id]
        info.append(
            {
                "id": method_id,
                "label": module.LABEL,
                "description": module.DESCRIPTION,
                "expected_index": module.EXPECTED_INDEX,
                **COMPARABILITY[method_id],
            }
        )
    return info


def validate_method(method: str) -> None:
    if method not in METHOD_MODULES:
        raise ValueError(
            f"Unknown method '{method}'. Choose one of: {', '.join(METHOD_ORDER)}"
        )


def validate_limit(limit: int) -> None:
    if limit not in Config.ALLOWED_LIMITS:
        raise ValueError(
            f"Limit must be one of {Config.ALLOWED_LIMITS} (Top 5 or Top 10)"
        )


OUT_OF_SCOPE_NOTICE = (
    "No products in this catalogue match that query. Try a product category, "
    "brand, colour, price range, or a feature such as \u201cwireless headphones\u201d."
)


def _warnings(method: str, outcome: dict, parsed: ParsedQuery) -> list[str]:
    warnings: list[str] = []
    plan = outcome.get("plan") or {}
    indexes = plan.get("indexes_used") or []
    details = outcome.get("method_details") or {}

    if method == "hash" and not parsed.brand:
        warnings.append(
            "No brand was parsed, so the brand hash index is not applicable. "
            "The plan may show a sequential scan."
        )
    if method == "composite_btree" and not parsed.category:
        warnings.append(
            "No category was parsed. Category is the leading column of the "
            "composite index, so the index is not applicable."
        )
    if method == "hnsw" and plan and not indexes:
        warnings.append(
            "EXPLAIN did not show an HNSW index scan for this query. The actual "
            "plan is shown instead of assuming vector index usage."
        )
    if method == "hybrid" and plan and not indexes:
        warnings.append(
            "EXPLAIN did not show an index scan. The actual plan is reported."
        )
    if method == "hybrid" and not details.get("structured_filter_count"):
        warnings.append(
            "No structured filters were parsed; hybrid search reduced to pure "
            "semantic search for this query."
        )
    if method == "cached" and outcome.get("cache", {}).get("status") == "hit":
        warnings.append(
            "Cache hit: database execution time is zero because no PostgreSQL "
            "query was executed."
        )
    if outcome.get("fallback"):
        warnings.append(outcome["fallback"]["note"])
    return warnings


def run_search(
    query: str,
    method: str,
    limit: int = 10,
    include_plan: bool = True,
    parsed: ParsedQuery | None = None,
    query_embedding: np.ndarray | None = None,
    parse_ms: float | None = None,
    embedding_ms: float | None = None,
) -> dict[str, Any]:
    validate_method(method)
    validate_limit(limit)

    wall_started = time.perf_counter()
    if parsed is None:
        parse_started = time.perf_counter()
        parsed = parse_query(query)
        parse_ms = (time.perf_counter() - parse_started) * 1000
    parse_ms = parse_ms or 0.0

    module = METHOD_MODULES[method]

    # Scope gate. A query must either name a category or brand, or contain
    # keywords that all exist in the catalogue. Colour and price are refinements,
    # not scope on their own: "blue shirt" must not return every blue product.
    # This stops unrelated prompts from receiving arbitrary nearest neighbours
    # from the vector methods and stops relational methods from scanning the
    # whole table for a query the catalogue cannot answer.
    if not (parsed.category or parsed.brand) and not keywords_match_exists(parsed.keywords):
        server_total_ms = (time.perf_counter() - wall_started) * 1000
        return {
            "query": parsed.original_query,
            "normalized_query": parsed.normalized_query,
            "method": method,
            "method_label": module.LABEL,
            "method_description": module.DESCRIPTION,
            "limit": limit,
            "execution_ms": round(parse_ms, 3),
            "db_execution_ms": 0.0,
            "embedding_ms": 0.0,
            "parse_ms": round(parse_ms, 3),
            "server_total_ms": round(server_total_ms, 3),
            "result_count": 0,
            "results": [],
            "parsed_filters": parsed.to_dict(),
            "cache": None,
            "technical": {
                "sql": None,
                "params": [],
                "planner_settings": [],
                "explain": None,
                "indexes_used": [],
                "rows_processed": None,
                "buffers": None,
                "plan_capture_ms": 0.0,
                "explain_error": None,
                "method_details": {},
                "fallback": None,
                "vector_info": None,
                "cache": None,
                "expected_index": module.EXPECTED_INDEX,
            },
            "comparability": COMPARABILITY[method],
            "warnings": [],
            "notice": OUT_OF_SCOPE_NOTICE,
            "out_of_scope": True,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }

    if method in {"hnsw", "hybrid"} and query_embedding is None:
        query_embedding, embedding_ms = encode_query(parsed.original_query)
    if embedding_ms is None:
        embedding_ms = 0.0

    if method in {"hnsw", "hybrid"}:
        outcome = module.search(
            parsed, limit, include_plan=include_plan, query_embedding=query_embedding
        )
    else:
        outcome = module.search(parsed, limit, include_plan=include_plan)

    # cached.search returns its own embedding time (0 on a hit).
    if method == "cached":
        embedding_ms = float(outcome.get("embedding_ms", 0.0))
    db_ms = float(outcome.get("db_execution_ms", 0.0))
    cache_lookup_ms = float((outcome.get("cache") or {}).get("lookup_ms", 0.0))
    execution_ms = parse_ms + embedding_ms + db_ms + cache_lookup_ms
    server_total_ms = (time.perf_counter() - wall_started) * 1000
    plan = outcome.get("plan") or {}

    technical = {
        "sql": outcome.get("sql"),
        "params": outcome.get("params"),
        "planner_settings": outcome.get("planner_settings", []),
        "explain": outcome.get("plan"),
        "indexes_used": plan.get("indexes_used", []),
        "rows_processed": plan.get("rows_returned_by_root"),
        "buffers": plan.get("buffers"),
        "plan_capture_ms": outcome.get("plan_capture_ms", 0.0),
        "explain_error": outcome.get("explain_error"),
        "method_details": outcome.get("method_details", {}),
        "fallback": outcome.get("fallback"),
        "vector_info": outcome.get("vector_info"),
        "cache": outcome.get("cache"),
        "expected_index": module.EXPECTED_INDEX,
    }

    result = {
        "query": parsed.original_query,
        "normalized_query": parsed.normalized_query,
        "method": method,
        "method_label": module.LABEL,
        "method_description": module.DESCRIPTION,
        "limit": limit,
        "execution_ms": round(execution_ms, 3),
        "db_execution_ms": round(db_ms, 3),
        "embedding_ms": round(embedding_ms, 3),
        "parse_ms": round(parse_ms, 3),
        "server_total_ms": round(server_total_ms, 3),
        "result_count": len(outcome.get("rows", [])),
        "results": outcome.get("rows", []),
        "parsed_filters": parsed.to_dict(),
        "cache": outcome.get("cache"),
        "technical": technical,
        "comparability": COMPARABILITY[method],
        "warnings": _warnings(method, outcome, parsed),
        "notice": None,
        "out_of_scope": False,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    return result
