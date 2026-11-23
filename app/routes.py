"""Flask API routes."""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from flask import Blueprint, Response, jsonify, render_template, request, send_file

from . import db
from .benchmark import FIXED_SUITE, benchmark_to_csv, run_benchmark
from .cache import cache
from .config import Config
from .embeddings import model_status
from .search import methods_info, run_search

api = Blueprint("api", __name__, url_prefix="/api")
pages = Blueprint("pages", __name__)


def error(message: str, status: int = 400, details=None):
    payload = {"error": message}
    if details is not None:
        payload["details"] = details
    return jsonify(payload), status


@pages.get("/")
def index():
    return render_template("index.html")


@api.get("/health")
def health():
    started = time.perf_counter()
    try:
        db_row = db.fetch_one(
            "SELECT version() AS version, current_database() AS database, "
            "current_user AS user"
        )
        vector_row = db.fetch_one(
            "SELECT extversion AS version FROM pg_extension WHERE extname = 'vector'"
        )
        counts = db.fetch_one(
            "SELECT count(*) AS products, "
            "count(embedding) AS embedded, "
            "count(DISTINCT category) AS categories FROM products"
        )
        categories = db.fetch_all(
            "SELECT category, count(*) AS count FROM products "
            "GROUP BY category ORDER BY category"
        )
        indexes = db.fetch_all(
            "SELECT indexname, indexdef FROM pg_indexes "
            "WHERE schemaname='public' AND tablename='products' "
            "ORDER BY indexname"
        )
        latency_ms = (time.perf_counter() - started) * 1000
    except Exception as exc:
        return (
            jsonify(
                {
                    "status": "degraded",
                    "healthy": False,
                    "error": str(exc),
                    "database_url": Config.DATABASE_URL.split("@")[-1],
                    "cache": cache.stats(),
                }
            ),
            503,
        )

    validation = None
    if Config.VALIDATION_JSON.exists():
        try:
            validation = json.loads(Config.VALIDATION_JSON.read_text(encoding="utf-8"))
        except Exception:
            validation = None

    return jsonify(
        {
            "status": "ok",
            "healthy": True,
            "app_version": "1.0.0",
            "project": {
                "title": "Indexed Product Search & Benchmarking System",
                "subtitle": (
                    "Compare database indexing and retrieval techniques on "
                    "100,000 synthetic products."
                ),
                "type": "DBMS academic project",
                "dataset_size": counts["products"],
                "database": "PostgreSQL + pgvector",
            },
            "database": {
                "version": db_row["version"].split(" on ")[0],
                "full_version": db_row["version"],
                "database": db_row["database"],
                "user": db_row["user"],
                "pgvector_version": vector_row["version"] if vector_row else None,
                "product_count": counts["products"],
                "embedded_count": counts["embedded"],
                "category_count": counts["categories"],
                "categories": categories,
                "indexes": indexes,
                "health_latency_ms": round(latency_ms, 3),
            },
            "embedding_model": model_status(),
            "cache": cache.stats(),
            "methods": methods_info(),
            "dataset_validation": validation,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
    )


@api.get("/methods")
def methods():
    return jsonify({"methods": methods_info()})


@api.post("/search")
def search():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return error("Request body must be a JSON object")

    query = payload.get("query")
    method = payload.get("method")
    limit = payload.get("limit", 10)
    include_plan = payload.get("include_plan", True)

    if not isinstance(query, str) or not query.strip():
        return error("'query' must be a non-empty string")
    if not isinstance(method, str) or not method:
        return error("'method' must be one of the seven supported method identifiers")
    if not isinstance(limit, int) or isinstance(limit, bool):
        return error("'limit' must be an integer (5 or 10)")
    if not isinstance(include_plan, bool):
        return error("'include_plan' must be a boolean")

    try:
        result = run_search(
            query, method, limit, include_plan=include_plan
        )
        return jsonify(result)
    except ValueError as exc:
        return error(str(exc))
    except Exception as exc:
        return error("Search failed", 500, {"type": type(exc).__name__, "message": str(exc)})


@api.post("/benchmark")
def benchmark():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return error("Request body must be a JSON object")

    query = payload.get("query")
    methods = payload.get("methods")
    limit = payload.get("limit", 10)
    repetitions = payload.get("repetitions", 5)
    clear_cache = payload.get("clear_cache", True)
    warmup_runs = payload.get("warmup_runs", 1)
    capture_plan = payload.get("capture_representative_plan", True)

    if not isinstance(query, str) or not query.strip():
        return error("'query' must be a non-empty string")
    if methods is not None and not isinstance(methods, list):
        return error("'methods' must be a list of method identifiers")
    if not isinstance(limit, int) or isinstance(limit, bool):
        return error("'limit' must be an integer (5 or 10)")
    if not isinstance(repetitions, int) or isinstance(repetitions, bool):
        return error("'repetitions' must be an integer")
    if not isinstance(clear_cache, bool):
        return error("'clear_cache' must be a boolean")
    if not isinstance(warmup_runs, int) or warmup_runs not in (0, 1):
        return error("'warmup_runs' must be 0 or 1")
    if not isinstance(capture_plan, bool):
        return error("'capture_representative_plan' must be a boolean")

    try:
        result = run_benchmark(
            query,
            methods=methods,
            limit=limit,
            repetitions=repetitions,
            clear_cache=clear_cache,
            warmup_runs=warmup_runs,
            capture_representative_plan=capture_plan,
        )
        return jsonify(result)
    except ValueError as exc:
        return error(str(exc))
    except Exception as exc:
        return error(
            "Benchmark failed", 500, {"type": type(exc).__name__, "message": str(exc)}
        )


@api.post("/benchmark/export")
def benchmark_export():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return error("Request body must be a JSON object")
    query = payload.get("query")
    if not isinstance(query, str) or not query.strip():
        return error("'query' must be a non-empty string")

    try:
        result = run_benchmark(
            query,
            methods=payload.get("methods"),
            limit=payload.get("limit", 10),
            repetitions=payload.get("repetitions", 5),
            clear_cache=payload.get("clear_cache", True),
            warmup_runs=payload.get("warmup_runs", 1),
            capture_representative_plan=payload.get("capture_representative_plan", False),
        )
    except ValueError as exc:
        return error(str(exc))
    except Exception as exc:
        return error(
            "Benchmark export failed", 500,
            {"type": type(exc).__name__, "message": str(exc)},
        )

    csv_data = benchmark_to_csv(result)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="benchmark_{stamp}.csv"'
        },
    )


@api.get("/benchmark/suite")
def benchmark_suite():
    return jsonify(
        {
            "queries": FIXED_SUITE,
            "methods": methods_info(),
            "repetitions_min": Config.MIN_BENCHMARK_REPETITIONS,
            "repetitions_max": Config.MAX_BENCHMARK_REPETITIONS,
        }
    )


@api.get("/benchmark/results.csv")
def benchmark_results_file():
    path = Config.DOCS_DIR / "benchmark_results.csv"
    if not path.exists():
        return error("Fixed-suite benchmark CSV has not been generated yet", 404)
    return send_file(path, mimetype="text/csv", as_attachment=True)


@api.get("/cache/stats")
def cache_stats():
    return jsonify(cache.stats())


@api.post("/cache/clear")
def cache_clear():
    cleared = cache.clear()
    return jsonify({"cleared_entries": cleared, "stats": cache.stats()})


@api.delete("/cache/clear")
def cache_clear_delete():
    cleared = cache.clear()
    return jsonify({"cleared_entries": cleared, "stats": cache.stats()})


@api.get("/products/<product_id>")
def product_detail(product_id: str):
    if not isinstance(product_id, str) or len(product_id) > 20:
        return error("Invalid product id")
    row = db.fetch_one(
        "SELECT product_id, name, category, brand, price_inr, color, rating, "
        "stock_quantity, use_case, specifications, description, tags, "
        "image_key, image_prompt FROM products WHERE product_id = %s",
        (product_id,),
    )
    if not row:
        return error("Product not found", 404)
    return jsonify(row)
