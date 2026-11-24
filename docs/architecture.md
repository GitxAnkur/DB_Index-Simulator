# System Architecture

## 1. Overview

The system is a single-machine Flask application with a PostgreSQL database. It has
two jobs:

1. **Product search** — accept a natural-language query, parse structured filters,
   run exactly the method the user selected, and return products plus technical
   evidence.
2. **Benchmarking** — run the same query through several methods repeatedly and
   return real per-run samples, statistics, plans, and CSV.

There is no simulation layer. Search results come from SQL executed through psycopg;
timings wrap actual `cursor.execute()` calls; plans come from
`EXPLAIN (ANALYZE, BUFFERS, VERBOSE, FORMAT JSON)`.

## 2. Component diagram

```text
Browser (HTML/CSS/JS + Chart.js)
        │  JSON over HTTP
        ▼
Flask app (run.py → app.create_app)
        │
        ├── routes.py ────────────── API + page routes
        │      │
        │      ├── query_parser.py ─ natural-language → ParsedQuery
        │      ├── embeddings.py ─── Sentence Transformers (384-d, CPU)
        │      ├── search/ ───────── seven method modules + dispatcher
        │      ├── benchmark.py ──── repetitions, statistics, CSV
        │      ├── cache.py ──────── TTL/LRU application cache
        │      └── plan.py ───────── EXPLAIN JSON normaliser
        │
        ├── db.py ───────────────── psycopg connection pool
        │
        ▼
PostgreSQL 19 + pgvector 0.8.7
  products (100,000 rows, VECTOR(384))
  B-tree, hash, composite, HNSW indexes
```

## 3. Request flow — search

`POST /api/search`:

1. **Validate** the JSON body: `query` non-empty string, `method` one of seven,
   `limit` in `(5, 10)`, `include_plan` boolean.
2. **Parse** the query (`query_parser.parse_query`) into a `ParsedQuery`:
   category, brand, colour, min/max price, use case, keywords, original and
   normalised query.
3. **Embed** only for `hnsw`, `hybrid`, and `cached`. The embedding is computed once
   per request and reused. Relational methods never load the model.
4. **Dispatch** to exactly one module in `app/search/`; the method is never
   auto-selected or silently substituted.
5. **Execute** a parameterised SQL statement inside a transaction. Optional
   `SET LOCAL` planner settings are fixed strings chosen by the method module.
6. **Capture the plan** with a *second* execution using `EXPLAIN ANALYZE`, so the
   reported query time is not inflated by plan capture. Plan-capture time is reported
   separately.
7. **Assemble** the response: results, parsed filters, timing breakdown, SQL,
   parameters, plan tree, indexes, buffers, method details, warnings, comparability.

Timing fields:

| Field | Meaning |
|---|---|
| `db_execution_ms` | Wall time around the actual result query only |
| `embedding_ms` | Query-embedding time (0 for relational methods) |
| `parse_ms` | Parser time |
| `execution_ms` | `parse_ms + embedding_ms + db_execution_ms + cache_lookup_ms` |
| `server_total_ms` | End-to-end server wall time for the request |
| `technical.plan_capture_ms` | Cost of the separate EXPLAIN execution |

`server_total_ms` is larger than `execution_ms` because it includes response
serialisation and framework overhead; the UI reports the components, not a single
unexplained number.

## 4. Request flow — benchmark

`POST /api/benchmark`:

1. Validate query, methods (non-empty, unique, known), limit, repetitions
   (5–20), cache flags, warm-up flag.
2. Load the embedding model **before timing** if any semantic method is selected.
3. Parse the query once and reuse the `ParsedQuery` for every method and repetition.
4. For each method:
   - compute the query embedding once (semantic methods);
   - clear the application cache before the cached method when requested;
   - run one unmeasured warm-up (non-cached methods) to warm PostgreSQL buffers;
   - run `repetitions` measured executions with `include_plan=False`;
   - record per-run DB time, total time, embedding time, server time, cache status,
     result count, success/error;
   - optionally run one extra execution with the plan captured as a representative
     plan (excluded from statistics).
5. Compute statistics from **successful DB times only**: median, mean, min, max,
   sample standard deviation, p95.
6. Compute result-set overlap against the full-scan reference (count and Jaccard).
7. Return conditions, raw samples, statistics, comparability notes, and a flat
   comparison table.

The benchmark deliberately does **not** hide failed runs: `successful_runs`,
`failed_runs`, and `errors` are returned, and the UI warns if any failed.

## 5. Module responsibilities

| Module | Responsibility |
|---|---|
| `app/__init__.py` | App factory, connection pool, cache configuration, background model warm-up, JSON error handlers |
| `app/config.py` | Environment-driven configuration and allowed limits |
| `app/db.py` | psycopg pool, `fetch_one`/`fetch_all`/`execute`, transaction context manager |
| `app/query_parser.py` | Rule-based parser, lexicon loaded from the DB, price expressions, synonyms, keyword extraction |
| `app/embeddings.py` | Lazy model load, `encode_query`, `to_pgvector`, `model_status` |
| `app/cache.py` | Thread-safe TTL + LRU cache with hit/miss/eviction/expiry statistics |
| `app/plan.py` | Flatten EXPLAIN JSON into nodes, indexes, seq/index scan counts, buffers |
| `app/benchmark.py` | Fixed suite, repetition runner, statistics, CSV serialisation |
| `app/routes.py` | All HTTP endpoints |
| `app/search/__init__.py` | Method registry, validation, warnings, response assembly |
| `app/search/base.py` | Shared SQL fragments, parameterised execution, EXPLAIN capture |
| `app/search/*.py` | One module per method |

## 6. The seven methods

| Method | SQL shape | Expected access path |
|---|---|---|
| `full_scan` | Structured `WHERE` + keyword `ILIKE`, index scans disabled | Seq Scan |
| `btree` | Same `WHERE`, planner free to choose | B-tree on category/price/rating |
| `hash` | Same `WHERE`, brand equality emphasized | Hash index on brand when present |
| `composite_btree` | Same `WHERE`, ordered by `price_inr, color` | `(category, price_inr, color)` B-tree |
| `hnsw` | `ORDER BY embedding <=> %s::vector LIMIT %s` | HNSW index |
| `hybrid` | Structured filters **and** vector `ORDER BY`, iterative HNSW | Relational index and/or HNSW, whatever the planner chooses |
| `cached` | TTL/LRU lookup around hybrid | No DB on a hit |


The “expected” index is metadata, not a guarantee. The actual `EXPLAIN` output is
always shown, and warnings are emitted when the expected access path is not used
(for example, a hash index with no brand predicate).

### Full scan isolation

To make the baseline meaningful, `full_scan` executes:

```sql
SET LOCAL enable_indexscan = off;
SET LOCAL enable_indexonlyscan = off;
SET LOCAL enable_bitmapscan = off;
SET LOCAL enable_seqscan = on;
```

These are fixed server-side settings, not user input. The plan confirms a
`Seq Scan`.

### Semantic methods

`hnsw` applies no structured filters. `hybrid` applies the parsed category, brand,
colour, and price filters and then orders the filtered rows by cosine distance. The
parser’s `use_case` is a **soft ranking hint** for hybrid (it is embedded in the
query text) and a **sort preference** for relational methods, not a hard `WHERE`
clause, because a user may ask for a use case that no product in the category
carries.

### Cache method

`cached` wraps `hybrid`. Its key is a hash of the normalised query, the result limit,
and the method name. A miss performs embedding + hybrid search and stores a deep copy
of the outcome; a hit returns a deep copy with `db_execution_ms = 0` and
`embedding_ms = 0`. TTL and LRU are enforced on every access. The cache is
in-process, so it is not shared between worker processes (documented limitation).

## 7. Scope gate and single-query execution

Before any method runs, the query is checked against the catalogue:

- it is in scope if it names a category or brand, or
- every keyword has a word-boundary match in `name`, `description`, `tags`,
  `specifications`, or `use_case` (practical synonyms allowed).

Colour and price alone are refinements, not scope. An out-of-scope query returns
`out_of_scope: true`, zero results, no SQL, and `db_execution_ms = 0`; the database
is never queried for it.

Relational methods apply structured filters **and** keyword `ILIKE` predicates in a
single SQL statement. There is no keyword-relaxation fallback, so repeated searches
are directly comparable and the reported time reflects exactly one execution.

Interactive searches send `include_plan: false`, so plan capture (`EXPLAIN`) is not
performed and cannot inflate the measured database time. The API and test suite can
still request plans explicitly.

## 8. Concurrency and state

- The psycopg connection pool is created once per process.
- The Sentence Transformers model is loaded lazily and guarded by a lock; the app
  also starts a background warm-up thread at startup.
- The cache uses a lock and is safe across Flask threads.
- Search requests are read-only. The only stateful operations are cache set/clear.
- Benchmarks run sequentially inside the request; this avoids contaminating timings
  with concurrent load.

## 9. Error handling

- Validation errors return HTTP 400 with `{"error": "..."}`.
- Unknown API routes and wrong HTTP methods return JSON 404/405, not HTML.
- Unexpected failures return HTTP 500 with an error type and message.
- The health endpoint returns HTTP 503 with `status: "degraded"` when the database is
  unreachable.
- Frontend errors are shown in an inline error box and a toast; the UI never silently
  displays stale results.

## 10. Frontend

Two pages:

1. **Search** (`templates/index.html`) — query input, example chips, method selector,
   Top 5/10 radio buttons, inline method hint, metric cards (DB execution time,
   result count, method, cache state), parsed-filter chips, warnings, and product
   cards. Out-of-scope queries show a notice and zero products.
2. **Analysis** (`templates/analysis.html`) — groups measurements by query ID. The
   selected query's chart compares only the methods that were manually run for it,
   and a list of all saved queries appears below; tapping a query reopens its graph.

The benchmark API remains available for academic measurement, but there is no
benchmark dashboard in the UI and no “under the hood” SQL/plan panel.

Chart.js is vendored at `static/vendor/chart.umd.min.js`, so the application works
without a CDN or internet connection.
