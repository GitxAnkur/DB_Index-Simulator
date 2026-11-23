# Benchmark Methodology

## 1. Goals

The benchmark answers a narrow, defensible question:

> For the same natural-language query, the same dataset, and the same result limit,
> how long does each retrieval method take on this machine, and what access path did
> PostgreSQL actually use?

It does **not** claim universal rankings. Results depend on hardware, PostgreSQL
version, cache state, data distribution, and query selectivity. The application
therefore reports conditions and raw samples alongside every summary.

## 2. Fixed query suite

`app/benchmark.py` defines seven queries covering the main predicate shapes:

| # | Query | Predicates exercised |
|---|---|---|
| 1 | `Samsung smartphone` | category + brand equality |
| 2 | `Laptops` | category equality |
| 3 | `Laptop under 80000` | category + price range |
| 4 | `Black laptop under 80000` | category + colour + price range |
| 5 | `Lightweight laptop for programming` | category + keyword text + use-case hint |
| 6 | `Wireless headphones for travel` | category + keyword text + use-case hint |
| 7 | `Gaming monitor under 30000` | category + price range + use-case hint |

The suite is exposed at `GET /api/benchmark/suite`. Any free-form query can also be
benchmarked through the UI or API.

## 3. Execution protocol

For each method, in the order selected:

1. **Parse once.** The query is parsed once and the same `ParsedQuery` is reused for
   every repetition. Parser time is measured separately and reported once.
2. **Embed once per semantic method.** For `hnsw`, `hybrid`, and `cached`, the query
   embedding is computed once before the repetitions. This isolates database
   execution from embedding cost. The one-time embedding time is reported at method
   level (`methods[].embedding_ms`). It is **not** added to each repetition’s
   `db_execution_ms`; adding it gives the end-to-end semantic request cost.
3. **Warm-up.** Non-cached methods run once unmeasured (`warmup_runs = 1`) to warm
   PostgreSQL shared buffers and the plan cache. The cached method is not warmed,
   because that would consume the miss that the experiment is trying to measure.
4. **Clear the application cache** before the cached method when
   `clear_cache = true` (the default). The number of cleared entries is reported.
5. **Measure `repetitions` executions** (5–20; default 5). Each measured execution
   uses `include_plan = false` so EXPLAIN does not inflate the timing.
6. **Capture one representative plan** after the measured runs, with
   `include_plan = true`. This extra execution is excluded from statistics and its
   cost is not included in `db_execution_ms`.
7. **Compute statistics** from successful `db_execution_ms` values only.
8. **Compare result sets** against the full-scan reference when both are present.

All executions are sequential. No other workload is deliberately run during a
benchmark, to avoid contaminating measurements.

## 4. What is measured

| Metric | Definition |
|---|---|
| `db_execution_ms` | Wall time around `cursor.execute(sql, params)` + `fetchall()` for the result query |
| `execution_ms` | `parse_ms + embedding_ms + db_execution_ms + cache_lookup_ms` for that request |
| `server_total_ms` | End-to-end server wall time for the sample (includes framework/serialisation) |
| `embedding_ms` | Query-embedding time; 0 for relational methods |
| `plan_capture_ms` | Cost of the separate `EXPLAIN ANALYZE` execution |

The primary comparison statistic is **`db_execution_ms`**. It is the part that the
database design change is supposed to affect, and it is measured identically for
relational and vector methods.

`server_total_ms` is retained in raw samples for transparency but is not the
headline number, because it includes HTTP/framework overhead unrelated to indexing.

## 5. Statistics

For `n` successful runs with values `x₁ … xₙ`:

- **Median** — `statistics.median(values)`; the primary statistic, robust to
  outliers.
- **Mean** — arithmetic mean.
- **Min / max** — observed extremes.
- **Standard deviation** — sample standard deviation (`n − 1` denominator); 0 for
  `n = 1`.
- **p95** — nearest-rank index `min(n − 1, round(0.95 × (n − 1)))`. With 5 or 10
  samples this typically equals the maximum; it is reported for completeness, not as
  a high-confidence tail estimate.

All values are rounded to 3 decimal places in the JSON and CSV.

Failed runs are **not** dropped silently. Each method reports `successful_runs`,
`failed_runs`, `errors`, and every sample has `success` and `error` fields. Statistics
are computed only over successful runs; if all runs fail, the statistics are `null`.

## 6. Cache conditions

The cached method changes state between runs, so its timing is only meaningful with
explicit cache conditions:

- The application cache is cleared before the cached method.
- Run 1 is a **miss**: it performs a real hybrid search (embedding + PostgreSQL).
- Runs 2…n are **hits**: no embedding, no database query.
- `cache_conditions` reports `hit_runs`, `miss_runs`, the ordered `statuses`, and
  whether the cache was cleared.
- The median is 0 ms when the majority of runs are hits. This is a true measurement
  of the hit path, not a fabricated timing. The miss sample is preserved in
  `samples` and in the CSV.

PostgreSQL’s own buffer cache is warm for all methods after the warm-up run. This is
stated in `conditions.postgres_cache`. Cold-start behaviour is **not** measured by
restarting PostgreSQL between runs; that would be a different experiment.

## 7. Comparability

Each method carries a comparability record:

| Group | Methods | Comparable to relational baseline? |
|---|---|---|
| Relational | `full_scan`, `btree`, `hash`, `composite_btree` | Yes — same filters, same ordering, same result semantics |
| Semantic | `hnsw`, `hybrid` | No — different result semantics, semantic ordering, embedding cost |
| Cache | `cached` | No — stateful; hit path avoids the database |

Even within the relational group, `full_scan` deliberately disables index scans, so
it is a controlled baseline rather than PostgreSQL’s default plan. This is stated in
the UI and in the method notes.

Result overlap is computed against the full-scan result set:

```json
"overlap_with_full_scan": {
  "overlap_count": 8,
  "jaccard": 0.6667,
  "reference_size": 10
}
```

This makes semantic/relational differences visible instead of implying that all
methods return the same rows.

## 8. CSV export

Two CSV paths exist:

1. **Per-run export** — `POST /api/benchmark/export` runs a fresh benchmark and
   streams a CSV attachment. One row per sample.
2. **Fixed-suite file** — `GET /api/benchmark/results.csv` serves
   `docs/benchmark_results.csv`, generated by `scripts/run_benchmarks.py`.

Columns:

```text
query, method, method_label, limit, repetition, success, execution_ms,
db_execution_ms, embedding_ms, total_ms, cache_status, result_count,
median_ms, mean_ms, min_ms, max_ms, stdev_ms, successful_runs,
failed_runs, comparable, overlap_with_full_scan, error
```

## 9. Recorded results

Generated by:

```bash
.venv/bin/python scripts/run_benchmarks.py --repetitions 5 --limit 10
```

Output files:

- `docs/benchmark_results.csv` — raw samples
- `docs/benchmark_summary.md` — median table
- `data/benchmark_results.json` — complete results and representative plans

Median database execution time (ms), 5 repetitions, limit 10:

| Query | Full scan | B-tree | Hash | Composite | HNSW | Hybrid | Cached |
|---|---:|---:|---:|---:|---:|---:|---:|
| Samsung smartphone | 10.378 | 0.886 | 0.763 | 0.747 | 0.558 | 3.453 | 0.000 |
| Laptops | 11.504 | 2.641 | 2.489 | 2.689 | 0.547 | 0.514 | 0.000 |
| Laptop under 80000 | 9.839 | 1.711 | 1.599 | 1.609 | 0.700 | 0.658 | 0.000 |
| Black laptop under 80000 | 9.333 | 0.728 | 0.608 | 0.576 | 1.088 | 1.644 | 0.000 |
| Lightweight laptop for programming | 23.813 | 17.054 | 16.706 | 19.946 | 0.593 | 0.606 | 0.000 |
| Wireless headphones for travel | 15.783 | 20.600 | 20.666 | 22.073 | 0.597 | 0.577 | 0.000 |
| Gaming monitor under 30000 | 10.129 | 1.670 | 1.501 | 1.490 | 0.863 | 0.937 | 0.000 |

These numbers are machine-specific. Re-running the script on different hardware will
produce different values; the methodology, not the absolute numbers, is the reusable
part.

## 10. Threats to validity

| Threat | Handling |
|---|---|
| Warm vs cold cache | One unmeasured warm-up; cache conditions reported |
| Background processes | Sequential runs; no deliberate concurrent load; raw samples retained |
| Approximate vector search | Recall caveat documented; `ef_search` reported |
| Embedding model load | Model loaded before timing; embedding reported separately |
| Planner choices | Actual plan captured and displayed; expected index is metadata only |
| Small sample size | 5 repetitions default, up to 20; median reported; p95 caveat stated |
| Different result semantics | Comparability flags and result overlap reported |
| Cache state | Cache cleared before cached method; miss/hit statuses retained |
| OS scheduling noise | Min/max/stdev shown; raw samples allow independent analysis |

## 11. Reproducing

```bash
bash scripts/start_postgres.sh
source .venv/bin/activate
python scripts/run_benchmarks.py --repetitions 5 --limit 10
pytest -q
```

Or use the UI: select methods, set repetitions, click **Run benchmark**, then
**Export CSV**.
