# Testing

## 1. Summary

The project has **86 pytest tests**, all passing against the real local PostgreSQL
database and the real embedding model. There are no database mocks and no fabricated
timings in the test path.

```text
86 passed in 7.03s
```

The suite is intentionally integration-heavy: it proves that the schema, dataset,
indexes, parser, seven methods, cache, benchmark runner, CSV export, and API error
handling work together.

## 2. Running the tests

Prerequisites:

```bash
bash scripts/start_postgres.sh
source .venv/bin/activate
```

Then:

```bash
pytest -q
```

or, if the virtual environment is not activated:

```bash
.venv/bin/python -m pytest -q
```

`pytest.ini` sets `testpaths = tests` and ignores deprecation warnings.

The tests require:

- 100,000 rows in `products`;
- 100,000 non-null 384-dimensional embeddings;
- the HNSW index and all relational indexes;
- `data/dataset_validation.json` present and passing.

They will fail on an empty database by design; they are not written to pass against
mocks.

## 3. Test files and coverage

| File | Tests | Focus |
|---|---:|---|
| `tests/conftest.py` | — | Session app fixture, client fixture, cache reset, lexicon reset, model preload |
| `tests/test_dataset.py` | 8 | Dataset size, IDs, category balance, nulls, ranges, embeddings, indexes, validation report |
| `tests/test_parser.py` | 21 | 15 parametrised parser cases + normalisation, no-invention, noise/brand ambiguity, multi-word brands, ambiguous prices, invalid input |
| `tests/test_search_methods.py` | 35 | All seven methods, limits, filters, plan evidence, hash/composite applicability, vector search, hybrid, fallback, cache, validation, SQL safety, product detail |
| `tests/test_benchmark.py` | 10 | Health, methods list, fixed suite, repetition statistics, cache conditions, validation, CSV export |
| `tests/test_cache.py` | 7 | Hit/miss, clear, key composition, isolation, TTL expiry, LRU eviction, configuration |
| `tests/test_api.py` | 5 | JSON 404/405, frontend HTML, database/extension, category distribution |

## 4. What is asserted

### Dataset integrity (`test_dataset.py`)

- Exactly 100,000 rows.
- 100,000 unique IDs from `P000001` to `P100000`.
- 10 categories × 10,000 rows each.
- No missing values in any column.
- Non-negative prices, ratings 0–5, non-negative stock.
- 100,000 embeddings, all dimension 384.
- All named indexes exist; brand index is `USING hash`; vector index is
  `USING hnsw` with `vector_cosine_ops`.
- `data/dataset_validation.json` reports `all_checks_passed: true`.

### Parser (`test_parser.py`)

- Category, brand, colour, min/max price, use case, and keyword extraction for 15
  representative queries.
- Original and normalised query preservation.
- No invented filters for a vague query.
- `noise cancelling headphones` does not misparse “noise” as a brand.
- Multi-word and hyphenated brands (`Ultimate Ears`, `Audio-Technica`).
- Ambiguous “around 50000” is not guessed.
- Empty, over-long, and non-string queries raise `ValueError`.

### Search methods (`test_search_methods.py`)

- All seven methods return results for a common query.
- `limit` is respected for 5 and 10.
- Structured filters are actually applied to returned rows.
- `full_scan` plan has no indexes and at least one Seq Scan.
- `btree` plan uses a B-tree.
- `hash` uses `idx_products_brand_hash` when a brand is present and reports
  non-applicability when it is not.
- `composite_btree` uses the composite index when category is present and reports the
  leading-column rule when it is absent.
- `hnsw` uses the HNSW index, reports cosine/384 dimensions, and returns similarities
  in [0, 1].
- `hybrid` applies structured filters and reports the filter count.
- Semantic search handles vocabulary absent from the dataset.
- Keyword fallback is reported, not hidden.
- `use_case` is a soft ranking preference, not a hard filter.
- Cache miss → hit transition, identical results, zero DB time on hit.
- Limit is part of the cache key.
- Unknown method, invalid limits, empty query, and non-JSON bodies return 400.
- SQL injection payload does not drop the table and does not appear in SQL text;
  user values appear only in `params`.
- Product detail returns 200/404 correctly.

### Benchmark (`test_benchmark.py`)

- Health reports 100,000 products, 100,000 embeddings, pgvector 0.8.7, seven methods,
  validation passed, and the HNSW index.
- `/api/methods` lists exactly seven methods in the expected order.
- Fixed suite contains seven queries and minimum 5 repetitions.
- A 7-method, 5-repetition benchmark returns 5 samples per method.
- Statistics equal independently recomputed median/mean/min/max.
- Every method has a representative plan.
- Cached method reports 1 miss + 4 hits with ordered statuses.
- Conditions record the limit and cache clearing.
- Repetitions outside 5–20, unknown methods, and empty method lists are rejected.
- CSV export has 10 rows for 2 methods × 5 repetitions, correct columns, and a
  download filename.
- Empty query export is rejected.

### Cache (`test_cache.py`)

- Hit/miss and shared key across identical queries.
- Zero database time on hit.
- Stats reflect hits/misses/entries.
- Clear endpoint removes entries and forces a miss.
- Query, limit, and method are part of the key.
- Other methods do not use the cache.
- TTL expiry increments `expirations`.
- LRU eviction removes the least recently used entry.
- Global cache is configured from the app.

### API (`test_api.py`)

- Unknown API endpoint returns JSON 404.
- Wrong method returns JSON 405.
- Root page serves the frontend with the expected title, benchmark section, and
  locally vendored Chart.js.
- PostgreSQL and pgvector are reachable.
- Category distribution is 10 × 10,000.

## 5. Design notes

- **Fixtures:** the app is created once per session; the model is loaded before the
  app to avoid a race with the background warm-up thread. The cache and lexicon are
  reset per test.
- **Real plans:** tests assert on plan content (`indexes_used`, `seq_scan_nodes`)
  where the plan is deterministic for the chosen query. The tests do not hardcode
  timings, because those vary by machine and load.
- **Isolation:** the suite never writes to the dataset. It only reads products and
  manipulates the in-process cache.
- **No network dependency after setup:** the model is cached locally; tests run
  offline once the model has been downloaded.

## 6. Known gaps

- No browser automation tests; the frontend was verified manually and with headless
  Chrome screenshots.
- No concurrent-load or stress test; the benchmark is deliberately sequential.
- No cold-start PostgreSQL measurement; cache state is warm and documented.
- HNSW recall is not measured against exact nearest neighbours; the project reports
  approximate results and the `ef_search` parameter rather than claiming exactness.
