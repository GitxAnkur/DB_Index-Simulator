# API Reference

Base URL: `http://127.0.0.1:5001`

All request bodies are JSON (`Content-Type: application/json`). All responses are
JSON except the CSV endpoints. Errors use `{"error": "message"}` and optionally
`details`.

Limits:

- `limit` must be exactly `5` or `10`.
- `repetitions` must be an integer from 5 to 20.
- Query strings must be non-empty and at most 500 characters.

---

## `GET /`

Serves the single-page frontend (`templates/index.html`).

---

## `GET /api/health`

Returns application, database, dataset, index, model, cache, and method status. This
endpoint never raises: if the database is unreachable it returns HTTP 503 with
`status: "degraded"`.

**Response (200, abridged):**

```json
{
  "status": "ok",
  "healthy": true,
  "app_version": "1.0.0",
  "database": {
    "version": "PostgreSQL 19.0",
    "pgvector_version": "0.8.7",
    "product_count": 100000,
    "embedded_count": 100000,
    "category_count": 10,
    "categories": [{"category": "Camera", "count": 10000}],
    "indexes": [{"indexname": "idx_products_embedding_hnsw", "indexdef": "..."}],
    "health_latency_ms": 3.12
  },
  "embedding_model": {"name": "sentence-transformers/all-MiniLM-L6-v2", "loaded": true},
  "cache": {"entries": 0, "hits": 0, "misses": 0, "ttl_seconds": 300},
  "methods": [{"id": "full_scan", "label": "Normal Search / Full Table Scan"}],
  "dataset_validation": {"rows": 100000, "all_checks_passed": true},
  "timestamp_utc": "2026-11-22T14:00:00+00:00"
}
```

**Response (503):**

```json
{"status": "degraded", "healthy": false, "error": "connection refused"}
```

---

## `GET /api/methods`

Returns metadata for exactly seven methods.

```json
{
  "methods": [
    {
      "id": "full_scan",
      "label": "Normal Search / Full Table Scan",
      "description": "...",
      "expected_index": "no index (sequential scan)",
      "comparable": true,
      "group": "relational",
      "note": "..."
    }
  ]
}
```

Method IDs, in order:

`full_scan`, `btree`, `hash`, `composite_btree`, `hnsw`, `hybrid`, `cached`.

---

## `POST /api/search`

Runs exactly one selected method.

**Request:**

```json
{
  "query": "Black laptop under 80000",
  "method": "composite_btree",
  "limit": 5,
  "include_plan": true
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `query` | string | yes | 1–500 characters |
| `method` | string | yes | one of the seven IDs |
| `limit` | integer | no | default 10; must be 5 or 10 |
| `include_plan` | boolean | no | default `true`; `false` skips EXPLAIN |

**Response (200, abridged):**

```json
{
  "query": "Black laptop under 80000",
  "normalized_query": "black laptop under 80000",
  "method": "composite_btree",
  "method_label": "Composite B+ Tree Search",
  "limit": 5,
  "execution_ms": 1.42,
  "db_execution_ms": 1.18,
  "embedding_ms": 0.0,
  "parse_ms": 0.19,
  "server_total_ms": 1.83,
  "result_count": 5,
  "results": [
    {
      "product_id": "P002176",
      "name": "MSI VivoBook Laptop",
      "category": "Laptop",
      "brand": "MSI",
      "price_inr": 74234.0,
      "color": "Black",
      "rating": 4.7,
      "stock_quantity": 42,
      "use_case": "everyday productivity",
      "specifications": "[\"16GB RAM\", ...]",
      "description": "...",
      "tags": "black, laptop, msi, ...",
      "image_key": "...",
      "image_prompt": "..."
    }
  ],
  "parsed_filters": {
    "category": "Laptop",
    "brand": null,
    "color": "Black",
    "min_price": null,
    "max_price": 80000.0,
    "use_case": null,
    "keywords": [],
    "matched_terms": ["black", "laptop", "under", "80000"],
    "has_structured_filters": true
  },
  "cache": null,
  "technical": {
    "sql": "SELECT ... FROM products WHERE category = %s AND color = %s AND price_inr <= %s ORDER BY ... LIMIT %s",
    "params": ["Laptop", "Black", 80000.0, 5],
    "planner_settings": [],
    "explain": {
      "execution_time_ms": 1.05,
      "planning_time_ms": 0.08,
      "top_node": "Limit",
      "indexes_used": ["idx_products_category_price_color_btree"],
      "seq_scan_nodes": 0,
      "index_scan_nodes": 1,
      "rows_returned_by_root": 5,
      "nodes": [
        {"depth": 0, "node_type": "Limit", "actual_rows": 5, "actual_total_ms": 1.05}
      ],
      "buffers": {"shared_hit_blocks": 21, "shared_read_blocks": 0}
    },
    "indexes_used": ["idx_products_category_price_color_btree"],
    "rows_processed": 5,
    "plan_capture_ms": 1.2,
    "method_details": {"leading_column_present": true},
    "fallback": null,
    "vector_info": null,
    "cache": null,
    "expected_index": "idx_products_category_price_color_btree"
  },
  "comparability": {"comparable": true, "group": "relational", "note": "..."},
  "warnings": [],
  "timestamp_utc": "2026-11-22T14:00:00+00:00"
}
```

Notes:

- `execution_ms = parse_ms + embedding_ms + db_execution_ms + cache_lookup_ms`.
- `technical.explain` is captured by a separate execution and is excluded from
  `db_execution_ms`.
- `technical.sql` contains only `%s` placeholders; user values are in
  `technical.params`.
- `warnings` reports non-applicable indexes, fallbacks, cache hits, and missing
  expected indexes.
- `technical.fallback` is non-null when a relational keyword filter was relaxed.

**Errors:**

| Status | Cause |
|---|---|
| 400 | non-object body, empty query, unknown method, non-integer/invalid limit, non-boolean `include_plan` |
| 500 | unexpected database/runtime error |

Example error:

```json
{"error": "Unknown method 'nope'. Choose one of: full_scan, btree, hash, composite_btree, hnsw, hybrid, cached"}
```

---

## `POST /api/benchmark`

Runs repeated real measurements and returns raw samples plus statistics.

**Request:**

```json
{
  "query": "Black laptop under 80000",
  "methods": ["full_scan", "btree", "hash", "composite_btree", "hnsw", "hybrid", "cached"],
  "limit": 10,
  "repetitions": 5,
  "clear_cache": true,
  "warmup_runs": 1,
  "capture_representative_plan": true
}
```

| Field | Type | Default | Notes |
|---|---|---|---|
| `query` | string | — | required |
| `methods` | list | all seven | non-empty, unique, known IDs |
| `limit` | integer | 10 | 5 or 10 |
| `repetitions` | integer | 5 | 5–20 |
| `clear_cache` | boolean | `true` | clears app cache before the cached method |
| `warmup_runs` | integer | 1 | 0 or 1 |
| `capture_representative_plan` | boolean | `true` | extra plan execution, excluded from stats |

**Response (200, abridged):**

```json
{
  "query": "Black laptop under 80000",
  "limit": 10,
  "repetitions": 5,
  "warmup_runs": 1,
  "parse_ms": 0.2,
  "started_at_utc": "2026-11-22T14:00:00+00:00",
  "finished_at_utc": "2026-11-22T14:00:01+00:00",
  "duration_seconds": 0.61,
  "methods": [
    {
      "method": "full_scan",
      "label": "Normal Search / Full Table Scan",
      "repetitions": 5,
      "warmup_runs": 1,
      "warmup_ms": 10.1,
      "embedding_ms": 0.0,
      "cache_cleared_entries": 0,
      "samples": [
        {
          "run": 1,
          "success": true,
          "execution_ms": 9.9,
          "db_execution_ms": 9.4,
          "embedding_ms": 0.0,
          "total_ms": 9.9,
          "server_total_ms": 10.2,
          "cache_status": null,
          "result_count": 10,
          "error": null
        }
      ],
      "stats": {
        "count": 5,
        "median_ms": 9.33,
        "mean_ms": 9.45,
        "min_ms": 9.11,
        "max_ms": 9.8,
        "stdev_ms": 0.27,
        "p95_ms": 9.8
      },
      "total_stats": {"median_ms": 9.9},
      "successful_runs": 5,
      "failed_runs": 0,
      "errors": [],
      "cache_conditions": {
        "hit_runs": 0,
        "miss_runs": 0,
        "statuses": [],
        "cache_cleared_before": false
      },
      "comparability": {"comparable": true, "group": "relational", "note": "..."},
      "result_ids": ["P002176", "..."],
      "representative_plan": {
        "execution_time_ms": 9.1,
        "top_node": "Limit",
        "indexes_used": [],
        "seq_scan_nodes": 1,
        "index_scan_nodes": 0,
        "rows_returned_by_root": 10,
        "buffers": {"shared_hit_blocks": 865}
      },
      "overlap_with_full_scan": {"overlap_count": 10, "jaccard": 1.0, "reference_size": 10}
    }
  ],
  "comparison_table": [
    {
      "method": "full_scan",
      "label": "Normal Search / Full Table Scan",
      "median_ms": 9.33,
      "mean_ms": 9.45,
      "min_ms": 9.11,
      "max_ms": 9.8,
      "stdev_ms": 0.27,
      "successful_runs": 5,
      "cache_state": "n/a",
      "comparable": true,
      "overlap_with_full_scan": 10
    }
  ],
  "conditions": {
    "same_query": true,
    "same_dataset": "100,000 synthetic products",
    "same_result_limit": 10,
    "postgres_cache": "warm (one unmeasured warm-up run for non-cached methods)",
    "application_cache": {"cleared_before_cached_method": true, "before": {}, "after": {}},
    "note": "..."
  }
}
```

Statistics are computed from **successful runs only** and from
`db_execution_ms`. Failed runs are counted and their messages listed in `errors`.

**Errors:** 400 for invalid query/methods/limit/repetitions/flags; 500 for unexpected
failures.

---

## `POST /api/benchmark/export`

Runs the same benchmark and streams a CSV attachment. The body accepts the same
fields as `/api/benchmark`; `capture_representative_plan` defaults to `false` here.

**Response (200):**

- `Content-Type: text/csv`
- `Content-Disposition: attachment; filename="benchmark_YYYYmmdd_HHMMSS.csv"`

CSV columns:

```text
query, method, method_label, limit, repetition, success, execution_ms,
db_execution_ms, embedding_ms, total_ms, cache_status, result_count,
median_ms, mean_ms, min_ms, max_ms, stdev_ms, successful_runs,
failed_runs, comparable, overlap_with_full_scan, error
```

One row per sample, so a 5-repetition, 3-method export has 15 data rows.

---

## `GET /api/benchmark/suite`

Returns the fixed seven-query suite and repetition bounds.

```json
{
  "queries": [
    "Samsung smartphone",
    "Laptops",
    "Laptop under 80000",
    "Black laptop under 80000",
    "Lightweight laptop for programming",
    "Wireless headphones for travel",
    "Gaming monitor under 30000"
  ],
  "methods": ["..."],
  "repetitions_min": 5,
  "repetitions_max": 20
}
```

---

## `GET /api/benchmark/results.csv`

Downloads the pre-generated fixed-suite CSV (`docs/benchmark_results.csv`). Returns
404 if it has not been generated.

---

## `GET /api/cache/stats`

```json
{
  "entries": 2,
  "max_entries": 512,
  "ttl_seconds": 300,
  "hits": 4,
  "misses": 2,
  "evictions": 0,
  "expirations": 0,
  "hit_rate": 0.667
}
```

---

## `POST /api/cache/clear` (also `DELETE /api/cache/clear`)

```json
{
  "cleared_entries": 2,
  "stats": {"entries": 0, "hits": 4, "misses": 2, "ttl_seconds": 300}
}
```

---

## `GET /api/products/<product_id>`

Returns one product. The `embedding` column is intentionally not returned.

**200:** product object with the same fields as a search result row.

**404:**

```json
{"error": "Product not found"}
```

---

## Error behaviour

| Status | Body |
|---|---|
| 400 | `{"error": "message"}` |
| 404 | `{"error": "Endpoint not found"}` or `{"error": "Product not found"}` |
| 405 | JSON 405 response |
| 500 | `{"error": "Search failed", "details": {"type": "...", "message": "..."}}` |
| 503 | health check degraded |

## SQL safety

Every user value is passed through psycopg’s parameter binding (`%s`). No user string
is interpolated into SQL. The only dynamically composed SQL fragments are fixed
column names and fixed planner `SET LOCAL` statements defined in code. The test suite
sends `laptop' OR 1=1; DROP TABLE products; --` and verifies that the table still has
100,000 rows and that the payload appears only in `params`.
