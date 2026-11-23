"""Benchmark runner: repeated real executions with raw samples and statistics."""
from __future__ import annotations

import csv
import io
import statistics
import time
from datetime import datetime, timezone
from typing import Any

import numpy as np

from .cache import cache
from .config import Config
from .embeddings import encode_query, get_model
from .query_parser import parse_query
from .search import (
    COMPARABILITY,
    METHOD_MODULES,
    METHOD_ORDER,
    methods_info,
    run_search,
    validate_limit,
    validate_method,
)

FIXED_SUITE = [
    "Samsung smartphone",
    "Laptops",
    "Laptop under 80000",
    "Black laptop under 80000",
    "Lightweight laptop for programming",
    "Wireless headphones for travel",
    "Gaming monitor under 30000",
]


def _stats(values: list[float]) -> dict[str, Any]:
    if not values:
        return {
            "count": 0,
            "median_ms": None,
            "mean_ms": None,
            "min_ms": None,
            "max_ms": None,
            "stdev_ms": None,
            "p95_ms": None,
        }
    ordered = sorted(values)
    p95_index = min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))
    return {
        "count": len(values),
        "median_ms": round(statistics.median(values), 3),
        "mean_ms": round(statistics.fmean(values), 3),
        "min_ms": round(min(values), 3),
        "max_ms": round(max(values), 3),
        "stdev_ms": round(statistics.stdev(values), 3) if len(values) > 1 else 0.0,
        "p95_ms": round(ordered[p95_index], 3),
    }


def _plan_summary(technical: dict) -> dict[str, Any] | None:
    plan = technical.get("explain")
    if not plan:
        return None
    return {
        "execution_time_ms": plan.get("execution_time_ms"),
        "planning_time_ms": plan.get("planning_time_ms"),
        "top_node": plan.get("top_node"),
        "indexes_used": plan.get("indexes_used", []),
        "seq_scan_nodes": plan.get("seq_scan_nodes"),
        "index_scan_nodes": plan.get("index_scan_nodes"),
        "rows_returned_by_root": plan.get("rows_returned_by_root"),
        "buffers": plan.get("buffers"),
    }


def run_benchmark(
    query: str,
    methods: list[str] | None = None,
    limit: int = 10,
    repetitions: int = 5,
    clear_cache: bool = True,
    warmup_runs: int = 1,
    capture_representative_plan: bool = True,
) -> dict[str, Any]:
    if not isinstance(query, str) or not query.strip():
        raise ValueError("Benchmark query must not be empty")
    if len(query) > 500:
        raise ValueError("Benchmark query must be at most 500 characters")
    if not isinstance(repetitions, int) or not (
        Config.MIN_BENCHMARK_REPETITIONS
        <= repetitions
        <= Config.MAX_BENCHMARK_REPETITIONS
    ):
        raise ValueError(
            f"Repetitions must be an integer between "
            f"{Config.MIN_BENCHMARK_REPETITIONS} and "
            f"{Config.MAX_BENCHMARK_REPETITIONS}"
        )
    validate_limit(limit)
    if methods is None:
        methods = list(METHOD_ORDER)
    if not isinstance(methods, list) or not methods:
        raise ValueError("Methods must be a non-empty list")
    if len(set(methods)) != len(methods):
        raise ValueError("Methods must not contain duplicates")
    for method in methods:
        validate_method(method)

    # Load the local model before timing so embedding measurements reflect
    # query encoding rather than one-time model initialisation.
    if any(method in {"hnsw", "hybrid", "cached"} for method in methods):
        get_model()

    parse_started = time.perf_counter()
    parsed = parse_query(query)
    parse_ms = (time.perf_counter() - parse_started) * 1000

    cache_before = cache.stats()
    started_at = datetime.now(timezone.utc)
    method_results: list[dict[str, Any]] = []

    for method in methods:
        module = METHOD_MODULES[method]
        query_embedding = None
        embedding_ms = 0.0
        if method in {"hnsw", "hybrid"}:
            query_embedding, embedding_ms = encode_query(parsed.original_query)

        cache_cleared = 0
        if method == "cached" and clear_cache:
            cache_cleared = cache.clear()

        warmup_ms = None
        if method != "cached" and warmup_runs > 0:
            try:
                warmup = run_search(
                    query,
                    method,
                    limit,
                    include_plan=False,
                    parsed=parsed,
                    query_embedding=query_embedding,
                    parse_ms=0.0,
                    embedding_ms=0.0,
                )
                warmup_ms = warmup["execution_ms"]
            except Exception as exc:  # pragma: no cover - defensive
                warmup_ms = None
                warmup_error = str(exc)
            else:
                warmup_error = None
        else:
            warmup_error = None

        samples: list[dict[str, Any]] = []
        errors: list[str] = []
        result_ids: list[str] | None = None
        cache_statuses: list[str] = []

        for run in range(1, repetitions + 1):
            sample_started = time.perf_counter()
            try:
                result = run_search(
                    query,
                    method,
                    limit,
                    include_plan=False,
                    parsed=parsed,
                    query_embedding=query_embedding,
                    parse_ms=0.0,
                    embedding_ms=0.0,
                )
                elapsed = (time.perf_counter() - sample_started) * 1000
                cache_status = (result.get("cache") or {}).get("status")
                if cache_status:
                    cache_statuses.append(cache_status)
                if result_ids is None:
                    result_ids = [r["product_id"] for r in result["results"]]
                sample = {
                    "run": run,
                    "success": True,
                    "execution_ms": result["execution_ms"],
                    "db_execution_ms": result["db_execution_ms"],
                    "embedding_ms": result["embedding_ms"],
                    "total_ms": round(
                        result["execution_ms"] + result["embedding_ms"], 3
                    ),
                    "server_total_ms": round(elapsed, 3),
                    "cache_status": cache_status,
                    "result_count": result["result_count"],
                    "error": None,
                }
            except Exception as exc:
                errors.append(str(exc))
                sample = {
                    "run": run,
                    "success": False,
                    "execution_ms": None,
                    "db_execution_ms": None,
                    "embedding_ms": None,
                    "total_ms": None,
                    "server_total_ms": None,
                    "cache_status": None,
                    "result_count": 0,
                    "error": str(exc),
                }
            samples.append(sample)

        successful = [s for s in samples if s["success"]]
        db_values = [s["db_execution_ms"] for s in successful]
        total_values = [s["total_ms"] for s in successful]

        representative_plan = None
        if capture_representative_plan:
            try:
                if method == "cached" and clear_cache:
                    cache.clear()
                plan_result = run_search(
                    query,
                    method,
                    limit,
                    include_plan=True,
                    parsed=parsed,
                    query_embedding=query_embedding,
                    parse_ms=0.0,
                    embedding_ms=0.0,
                )
                representative_plan = _plan_summary(plan_result["technical"])
            except Exception as exc:  # pragma: no cover - defensive
                representative_plan = {"error": str(exc)}

        method_results.append(
            {
                "method": method,
                "label": module.LABEL,
                "description": module.DESCRIPTION,
                "expected_index": module.EXPECTED_INDEX,
                "repetitions": repetitions,
                "warmup_runs": warmup_runs if method != "cached" else 0,
                "warmup_ms": warmup_ms,
                "warmup_error": warmup_error,
                "embedding_ms": round(embedding_ms, 3),
                "cache_cleared_entries": cache_cleared,
                "samples": samples,
                "stats": _stats(db_values),
                "total_stats": _stats(total_values),
                "successful_runs": len(successful),
                "failed_runs": len(samples) - len(successful),
                "errors": errors,
                "cache_conditions": {
                    "hit_runs": cache_statuses.count("hit"),
                    "miss_runs": cache_statuses.count("miss"),
                    "statuses": cache_statuses,
                    "cache_cleared_before": bool(cache_cleared),
                },
                "comparability": COMPARABILITY[method],
                "result_ids": result_ids,
                "representative_plan": representative_plan,
            }
        )

    # Result-set overlap against the full-scan reference (when available).
    reference = next(
        (m for m in method_results if m["method"] == "full_scan" and m["result_ids"]),
        None,
    )
    for item in method_results:
        ids = item.get("result_ids") or []
        if reference and ids:
            ref_ids = set(reference["result_ids"])
            overlap = len(ref_ids.intersection(ids))
            item["overlap_with_full_scan"] = {
                "overlap_count": overlap,
                "jaccard": round(
                    overlap / len(ref_ids.union(ids)), 4
                ) if ref_ids.union(ids) else 0.0,
                "reference_size": len(ref_ids),
            }
        else:
            item["overlap_with_full_scan"] = None

    cache_after = cache.stats()
    finished_at = datetime.now(timezone.utc)
    comparison_table = [
        {
            "method": m["method"],
            "label": m["label"],
            "median_ms": m["stats"]["median_ms"],
            "mean_ms": m["stats"]["mean_ms"],
            "min_ms": m["stats"]["min_ms"],
            "max_ms": m["stats"]["max_ms"],
            "stdev_ms": m["stats"]["stdev_ms"],
            "successful_runs": m["successful_runs"],
            "cache_state": (
                "hit" if m["cache_conditions"]["hit_runs"]
                else "miss" if m["cache_conditions"]["miss_runs"]
                else "n/a"
            ),
            "comparable": m["comparability"]["comparable"],
            "overlap_with_full_scan": (
                m["overlap_with_full_scan"]["overlap_count"]
                if m["overlap_with_full_scan"] else None
            ),
        }
        for m in method_results
    ]

    return {
        "query": parsed.original_query,
        "normalized_query": parsed.normalized_query,
        "parsed_filters": parsed.to_dict(),
        "limit": limit,
        "repetitions": repetitions,
        "warmup_runs": warmup_runs,
        "parse_ms": round(parse_ms, 3),
        "started_at_utc": started_at.isoformat(timespec="seconds"),
        "finished_at_utc": finished_at.isoformat(timespec="seconds"),
        "duration_seconds": round((finished_at - started_at).total_seconds(), 3),
        "methods": method_results,
        "comparison_table": comparison_table,
        "methods_info": methods_info(),
        "conditions": {
            "same_query": True,
            "same_dataset": "100,000 synthetic products",
            "same_result_limit": limit,
            "postgres_cache": "warm (one unmeasured warm-up run for non-cached methods)",
            "application_cache": {
                "cleared_before_cached_method": clear_cache,
                "before": cache_before,
                "after": cache_after,
            },
            "note": (
                "Median is the primary comparison statistic. Semantic methods "
                "return different result semantics and include embedding work; "
                "the cached method changes state between runs. See comparability."
            ),
        },
    }


def benchmark_to_csv(result: dict[str, Any]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "query",
            "method",
            "method_label",
            "limit",
            "repetition",
            "success",
            "execution_ms",
            "db_execution_ms",
            "embedding_ms",
            "total_ms",
            "cache_status",
            "result_count",
            "median_ms",
            "mean_ms",
            "min_ms",
            "max_ms",
            "stdev_ms",
            "successful_runs",
            "failed_runs",
            "comparable",
            "overlap_with_full_scan",
            "error",
        ]
    )
    for method in result["methods"]:
        stats = method["stats"]
        overlap = method.get("overlap_with_full_scan") or {}
        for sample in method["samples"]:
            writer.writerow(
                [
                    result["query"],
                    method["method"],
                    method["label"],
                    result["limit"],
                    sample["run"],
                    sample["success"],
                    sample["execution_ms"],
                    sample["db_execution_ms"],
                    sample["embedding_ms"],
                    sample["total_ms"],
                    sample["cache_status"],
                    sample["result_count"],
                    stats["median_ms"],
                    stats["mean_ms"],
                    stats["min_ms"],
                    stats["max_ms"],
                    stats["stdev_ms"],
                    method["successful_runs"],
                    method["failed_runs"],
                    method["comparability"]["comparable"],
                    overlap.get("overlap_count"),
                    sample["error"],
                ]
            )
    return buffer.getvalue()


def run_fixed_suite(
    repetitions: int = 5, limit: int = 10, methods: list[str] | None = None
) -> list[dict[str, Any]]:
    return [
        run_benchmark(
            query,
            methods=methods,
            limit=limit,
            repetitions=repetitions,
            clear_cache=True,
        )
        for query in FIXED_SUITE
    ]
