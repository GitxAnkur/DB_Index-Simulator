# Project Presentation Guide

**Project:** Indexed Product Search — A Comparative Study of Database Indexing Techniques  
**Stack:** Flask + Python 3.12 + PostgreSQL 19 + pgvector 0.8.7 + Sentence Transformers + Chart.js  
**Dataset:** 100,000 synthetic products, 384-dimensional embeddings  
**Team:** three members (replace the placeholder names below with your real names)

Use this document as the single source of truth for the presentation. It explains
what to say, what happens in the background, which files prove each claim, how to
demo the application, and how to divide the work fairly.

**How to use this document**

- Sections 0–15 are the presentation script: pitch, architecture, request lifecycle,
  index mechanisms, demo, work division, slide outline, and viva answers.
- Section 16 tells the full **idea-to-final-project** story: the original problem,
  requirements, design decisions and alternatives, development phases, the bugs we
  hit, and how the project changed over time. Read this if the professor asks
  “how did you get here?” or “why did you build it this way?”.
- Section 17 is the repository map and a from-scratch setup guide.
- Section 18 is a glossary of every DBMS and project term used in the presentation.
- Section 19 gives 3-minute, 8-minute, and 12-minute delivery plans mapped to slides.

---

## 0. The 30-second pitch

> We built a product-search system that lets a user choose a database retrieval
> method and immediately see how PostgreSQL actually executes that query. We compare
> four relational access paths (full scan, B+ tree, hash, and composite index), a
> vector index, a hybrid search, and an application cache on 100,000 products. Every number comes from real
> SQL execution, not a hard-coded table. The system also groups measurements by query,
> so the same query can be compared across every index the user tried.

---

## 1. The five points the professor should remember

1. **The database is real.** PostgreSQL stores 100,000 products and 100,000
   384-dimensional embeddings. All timings are measured around actual SQL execution.
2. **Seven retrieval methods are implemented separately** and manually selected by
   the user: Full Table Scan, B+ Tree, Hash Index, Composite Index, HNSW Vector
   Search, Hybrid, and Cached Search.
3. **The parser turns natural language into safe, parameterised SQL.** The user's
   text never becomes SQL text.
4. **The system is honest about what the planner did.** The API reports the indexes
   that PostgreSQL actually used; it does not pretend an index was used.
5. **The analysis page is query-specific.** Each query has a stable ID; adding a new
   method to the same query adds a bar to that query's graph, while a different query
   gets a different graph.

---

## 2. System at a glance

### 2.1 Technology stack

| Layer | Technology | Purpose |
|---|---|---|
| Database | PostgreSQL 19, pgvector 0.8.7 | Relational data, B-tree/hash/composite indexes, HNSW vector index |
| Embeddings | `sentence-transformers/all-MiniLM-L6-v2` | Converts product text and user queries into 384-dimensional vectors |
| Backend | Python 3.12, Flask 3.1, psycopg 3 | API, query parsing, search dispatch, timing, caching |
| Frontend | HTML, CSS, vanilla JavaScript, Chart.js | Search UI, result cards, query-specific analysis dashboard |
| Dataset | 100,000-row synthetic CSV | Reproducible, controlled benchmark workload |
| Testing | pytest | 101 tests against the real database |

### 2.2 Architecture diagram

```text
┌──────────────────────────────────────────────────────────────┐
│ Browser                                                       │
│  Search page (/)          Analysis page (/analysis)           │
│  - query, method, limit   - one graph per query ID            │
│  - result cards           - clickable saved-query list        │
│  - Chart.js               - table of methods tested           │
└───────────────┬───────────────────────────────▲──────────────┘
                │ POST /api/search                │ JSON response
                │ {query, method, limit,          │ {results,
                │  include_plan:false}            │  db_execution_ms, ...}
                ▼                                 │
┌──────────────────────────────────────────────────────────────┐
│ Flask application                                             │
│  routes.py → run_search()                                     │
│      1. validate request                                      │
│      2. query_parser.parse_query() → structured filters       │
│      3. scope gate → reject unrelated queries (no DB query)   │
│      4. embeddings.encode_query() for HNSW/hybrid only        │
│      5. search dispatcher → selected method module            │
│      6. base.execute_sql() → parameterised SQL + timing       │
│      7. assemble response / warnings / cache status           │
└───────────────┬───────────────────────────────────────────────┘
                │ psycopg connection pool
                ▼
┌──────────────────────────────────────────────────────────────┐
│ PostgreSQL 19 + pgvector                                      │
│  products table: 100,000 rows, 100,000 embeddings              │
│  indexes: PK, price/category/rating B-trees, brand hash,      │
│           (category, price_inr, color) composite, HNSW        │
└──────────────────────────────────────────────────────────────┘
```

### 2.3 Where the code lives

| File / folder | Responsibility |
|---|---|
| `app/routes.py` | HTTP endpoints: `/api/search`, `/api/health`, `/api/methods`, benchmark, cache, product detail |
| `app/query_parser.py` | Rule-based natural-language parsing and the scope gate |
| `app/search/__init__.py` | Method registry, validation, response assembly, warnings |
| `app/search/base.py` | Shared SQL construction, parameterised execution, timing, EXPLAIN capture |
| `app/search/full_scan.py` | Method 1: controlled sequential scan |
| `app/search/btree.py` | Method 2: B+ Tree / PostgreSQL B-tree method |
| `app/search/hash_index.py` | Method 3: hash index method |
| `app/search/composite_btree.py` | Method 4: composite index method |
| `app/search/hnsw.py` | Method 5: vector search |
| `app/search/hybrid.py` | Method 6: relational filters + vector ranking |
| `app/search/cached.py` | Method 7: TTL/LRU application cache |
| `app/embeddings.py` | Local Sentence Transformers model and query encoding |
| `app/cache.py` | Thread-safe in-memory TTL + LRU cache |
| `app/plan.py` | Parses `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` output |
| `app/benchmark.py` | Repeated measurements, statistics, CSV export |
| `app/db.py` | psycopg connection pool and query helpers |
| `scripts/schema.sql` | Table and index definitions |
| `scripts/init_db.py`, `import_data.py`, `generate_embeddings.py` | Database setup pipeline |
| `templates/index.html`, `static/js/app.js` | Search page and browser logic |
| `templates/analysis.html`, `static/js/analysis.js` | Query-specific analysis dashboard |
| `tests/` | 101 integration tests against the real database |

---

## 3. End-to-end request lifecycle (what happens in the background)

This is the most important section for the professor. Walk through it slowly.

### Step 1 — Browser sends a search request

The frontend sends:

```json
{
  "query": "black laptop under 80000",
  "method": "composite_btree",
  "limit": 5,
  "include_plan": false
}
```

`include_plan` is `false` for interactive searches. This is deliberate: capturing an
`EXPLAIN ANALYZE` plan would execute the query a second time and distort the measured
time. The API can still request plans explicitly for inspection and tests.

### Step 2 — Flask validates the request

`app/routes.py` checks that the body is a JSON object, the query is a non-empty
string, the method is one of the seven supported IDs, `limit` is 5 or 10, and
`include_plan` is a boolean. Invalid input gets HTTP 400 with a JSON error.

### Step 3 — The parser extracts structured filters

`app/query_parser.py` is rule-based, not an LLM. It extracts only what is explicitly
present:

- category, using synonyms (`laptops` → `Laptop`, `phones` → `Smartphone`)
- brand, using the database brand lexicon and multi-word handling
- colour (`black`, `blue`, `silver`, ...)
- price bounds (`under 80000`, `between 20000 and 50000`)
- use case (`gaming`, `programming`, `photography`, ...)
- remaining keywords (`wireless`, `lightweight`, ...)

It never invents a filter. The original and normalised query are preserved.

### Step 4 — Scope gate: reject unrelated queries before touching the database

A query is **in scope** if:

- it names a category or brand, **or**
- every keyword has a word-boundary match in the product text
  (`name`, `description`, `tags`, `specifications`, `use_case`), with practical
  synonyms allowed.

Colour and price alone are refinements, not scope. For example, `blue shirt` must not
return every blue product. `pet food` must not match `competitive`.

The scope check uses a cheap `ILIKE` prefilter plus a word-boundary regex, and its
result is cached in-process for 300 seconds. An out-of-scope query returns:

```json
{
  "out_of_scope": true,
  "result_count": 0,
  "db_execution_ms": 0.0,
  "technical": {"sql": null},
  "notice": "No products in this catalogue match that query..."
}
```

No SQL is executed. This is why out-of-scope searches return zero results instead of
arbitrary nearest neighbours.

### Step 5 — Embed the query only for semantic methods

For `hnsw` and `hybrid`, `app/embeddings.py` runs the local
`all-MiniLM-L6-v2` model on CPU and returns a normalised 384-dimensional vector. The
model is loaded once and warmed at startup. Embedding time is measured and reported
separately.

### Step 6 — Dispatch to exactly one search module

`app/search/__init__.py` maps the method ID to one module. There is no automatic
method selection and no hidden fallback to another method.

### Step 7 — Build and execute one SQL statement

Relational methods share `structured_conditions()` and `relational_sql()` in
`app/search/base.py`. Every user value is passed as a `%s` parameter. The database
driver sends the SQL text and values separately, so SQL injection is prevented.

`execute_sql()` measures only the actual result query:

```python
started = time.perf_counter()
cur.execute(sql, params)
rows = list(cur.fetchall())
db_ms = (time.perf_counter() - started) * 1000
```

If a plan was requested, `EXPLAIN (ANALYZE, BUFFERS, VERBOSE, FORMAT JSON)` runs
afterward and its cost is reported separately as `plan_capture_ms`, never added to
`db_execution_ms`.

### Step 8 — The response is assembled

The response includes:

- `db_execution_ms` — time inside PostgreSQL for the result query
- `execution_ms` — parse + embedding + DB + cache lookup
- `embedding_ms`, `parse_ms`, `server_total_ms`
- `result_count`, `results`
- `parsed_filters`
- cache status for the cached method
- `warnings` (for example, hash index not applicable)
- `technical` metadata when a plan was requested
- `out_of_scope` and `notice`

### Step 9 — The browser renders and records the measurement

The search page renders metric cards and product cards. It also records the latest
measurement for this query and method in `localStorage` under a stable query ID. The
Analysis page later reads that store and draws the graph.

### 3.1 Why repeated timings are almost stable

- Interactive searches execute exactly one SQL statement.
- Plan capture is disabled (`include_plan: false`), so there is no hidden second
  execution.
- The model and each index are warmed once at startup, then the app cache is cleared.
- The connection pool is already open.
- There is no keyword-relaxation retry.

The one intentional exception is **Cached Search**: the first run is a miss and
repeated runs are hits with 0 ms database time. That is the behaviour being measured.

---

## 4. Dataset and database design

### 4.1 Dataset facts

| Property | Value |
|---|---|
| Rows | 100,000 |
| Categories | 10 × 10,000 each |
| Brands | 45 |
| Use cases | 39 |
| Colours | Black, Blue, Green, Grey, Red, Silver, White |
| Price range | ₹501 – ₹279,993 (mean ≈ ₹60,490) |
| Rating range | 2.8 – 5.0 (mean ≈ 3.898) |
| Stock | 0 – 150 |
| Product IDs | `P000001` – `P100000`, unique |
| Embeddings | 100,000 × 384 dimensions |
| Validation | All checks pass (`data/dataset_validation.json`) |

The data is synthetic and controlled, so every student benchmarks the same workload.
It is explicitly **not real retail inventory**.

### 4.2 Table design

`scripts/schema.sql` creates one `products` table:

- `product_id` primary key
- `name`, `category`, `brand`, `price_inr`, `color`, `rating`, `stock_quantity`
- `use_case`, `specifications`, `description`, `tags`
- `image_key`, `image_prompt` (reserved for a future image feature)
- `embedding VECTOR(384)` from pgvector
- `CHECK` constraints for non-negative price/stock and rating 0–5

### 4.3 Index inventory (verified live)

All seven indexes are `indisvalid = true` and `indisready = true`.

| Index | Type | Columns / options | Approx. size |
|---|---|---|---:|
| `products_pkey` | B-tree | `product_id` | 4.4 MB |
| `idx_products_price_btree` | B-tree | `price_inr` | 4.1 MB |
| `idx_products_category_btree` | B-tree | `category` | 1.7 MB |
| `idx_products_rating_btree` | B-tree | `rating` | 3.1 MB |
| `idx_products_brand_hash` | Hash | `brand` | 6.6 MB |
| `idx_products_category_price_color_btree` | B-tree (composite) | `(category, price_inr, color)` | 10 MB |
| `idx_products_embedding_hnsw` | HNSW | `embedding vector_cosine_ops`, `m=16`, `ef_construction=64` | 191 MB |

**How to prove it during the demo:** `GET /api/health` returns the live index list and
definitions from `pg_indexes`. A direct SQL query on `pg_index` proves validity and
readiness.

---

## 5. The seven methods and how each index mechanism is implemented

Use this table as the backbone of the technical explanation.

| # | Method | Main implementation | What PostgreSQL does |
|---:|---|---|---|
| 1 | Full Table Scan | `full_scan.py` | Sequential scan with index/bitmap scans disabled |
| 2 | B+ Tree | `btree.py` | Planner chooses a single-column B-tree on category, price, or rating |
| 3 | Hash Index | `hash_index.py` | Hash index on `brand` for equality only |
| 4 | Composite Index | `composite_btree.py` | Multicolumn B-tree `(category, price_inr, color)` with leading-column rule |
| 5 | HNSW Vector Search | `hnsw.py` | pgvector HNSW graph, cosine distance `<=>` |
| 6 | Hybrid | `hybrid.py` | Structured filters plus vector ordering, iterative HNSW scan |
| 7 | Cached Search | `cached.py` | Application TTL/LRU cache in front of hybrid; no DB on a hit |

### 5.1 Full Table Scan

`full_scan.py` executes the same relational SQL as the other methods, but inside a
transaction it sets:

```sql
SET LOCAL enable_indexscan = off;
SET LOCAL enable_indexonlyscan = off;
SET LOCAL enable_bitmapscan = off;
SET LOCAL enable_seqscan = on;
```

This creates a controlled baseline. It is not a claim about PostgreSQL's default plan;
it is deliberately forced so the class can see the cost of reading the table without
index access paths.

### 5.2 B+ Tree

PostgreSQL implements **B-tree** indexes, which serve the B+ tree concept taught in
class. The schema has three single-column B-trees:

```sql
CREATE INDEX idx_products_price_btree    ON products USING btree (price_inr);
CREATE INDEX idx_products_category_btree ON products USING btree (category);
CREATE INDEX idx_products_rating_btree   ON products USING btree (rating);
```

The B+ Tree method does not force one index. It runs the relational query and lets the
planner choose among the available B-trees. The actual index is reported from the
plan. This is important: the label describes the intended index family, not a
restriction on PostgreSQL.

B-trees accelerate equality, range, and ordered retrieval. They do **not** accelerate
`ILIKE '%keyword%'`, because a leading wildcard cannot use the sorted key order.

### 5.3 Hash Index

```sql
CREATE INDEX idx_products_brand_hash ON products USING hash (brand);
```

A hash index is designed for equality (`brand = %s`). It cannot serve ranges or
ordering. If the query has no brand, the method reports `hash_index_applicable: false`
and warns the user instead of pretending the index was used.

### 5.4 Composite Index

```sql
CREATE INDEX idx_products_category_price_color_btree
    ON products USING btree (category, price_inr, color);
```

Key teaching points:

- **Leading-column rule:** the index is usable when `category` is constrained.
  Without category, it is reported as not applicable.
- **Column order matters:** after a range on `price_inr`, the later `color` column is
  generally applied as a filter rather than a tight index bound.
- The method orders results by `price_inr, color, product_id` so the composite index
  can serve both filtering and ordering in one pass.

### 5.5 HNSW Vector Search

```sql
CREATE INDEX idx_products_embedding_hnsw
    ON products USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);
```

SQL shape:

```sql
SELECT ..., 1 - (embedding <=> %s::vector) AS similarity
FROM products
WHERE embedding IS NOT NULL
ORDER BY embedding <=> %s::vector
LIMIT %s;
```

- `<=>` is pgvector's cosine-distance operator.
- `SET LOCAL hnsw.ef_search = 100` controls the query-time candidate list.
- HNSW is **approximate**: recall depends on `m`, `ef_construction`, and `ef_search`.
- Results below cosine similarity `0.30` are discarded as a second safety net.
- HNSW applies no structured filters.

### 5.6 Hybrid (Filters + Vector)

Hybrid applies parsed category/brand/colour/price predicates in SQL and then orders the
remaining rows by cosine distance.

The important implementation detail is:

```sql
SET LOCAL hnsw.iterative_scan = relaxed_order;
```

HNSW normally filters **after** the graph scan. With a selective filter, the nearest
`ef_search` candidates can all fail the predicate, producing an empty result set.
Iterative scanning lets pgvector continue through the graph until enough filtered rows
are found. This was a real bug found during development and fixed with the setting.

`use_case` remains a soft ranking hint in the embedded query text, not a hard `WHERE`
clause, because a user may ask for a use case that no product in the category carries.

### 5.7 Cached Search

The cache is **not** a database index. It is an in-process TTL + LRU cache:

- key: SHA-256 of `method | normalised query | limit`
- TTL: 300 seconds
- capacity: 512 entries, LRU eviction
- miss: run hybrid search and store a deep copy
- hit: return a deep copy with `db_execution_ms = 0`

This demonstrates a different optimisation trade-off: speed for repeated queries at
the cost of memory and possible staleness. It is not shared across worker processes.

---

## 6. Query parser and scope gate in one slide

**Parser:** rule-based extraction of category, brand, colour, price, use case, and
keywords. Synonyms map user language to catalogue labels. No invented filters.

**Scope gate:** prevents the system from answering questions the catalogue cannot
answer.

- In scope: category or brand present, or every keyword matches product text.
- Out of scope: return zero results, no SQL, zero DB time.
- The scope check is cached for 300 seconds.
- HNSW similarity floor is a second safety net.

**Why this matters:** a vector index always returns *some* nearest neighbours. Without
a scope gate, `flying car` would return five random products. The gate makes the
system behave like a catalogue search, not a random-neighbour generator.

---

## 7. Query-specific analysis dashboard

This is the feature that makes the project a measurement tool rather than a search
demo.

### How it works

1. After a search, the browser computes a stable query ID:
   `Q-XXXXXX` from a hash of the normalised query and the limit.
2. It stores the latest result for that method under that query ID in `localStorage`:
   `dbms2.analysis.queries.v1`.
3. Running the **same query** with a different method adds/updates one bar in the same
   query's graph.
4. Running a **different query** creates a different query ID and a different graph.
5. The search result page shows the query ID and a `View Q-XXXXXX analysis` link.
6. `/analysis` shows the selected query's graph, a summary, a method table, and a
   clickable list of all saved queries below.
7. Clicking a query card switches the graph. Deep links work:
   `/analysis?q=Q-XXXXXX`.
8. The last search is remembered (`dbms2.lastSearch.v1`), so returning to Search keeps
   the query prefilled for a method-to-method comparison.

### What the graph shows

- One bar per **manually selected method** for that query.
- Bar height = `db_execution_ms` (actual PostgreSQL query time).
- Tooltip shows result count.
- Table shows DB time, result count, cache status, and measurement time.

It deliberately does **not** show embedding time in the bar, because the comparison is
about database index performance. Embedding time is reported separately in the API.

---

## 8. Benchmarking, testing, and correctness evidence

### Benchmark API (kept for academic measurement, not shown in the UI)

- `POST /api/benchmark` runs a method 5–20 times, returns raw samples and statistics:
  median, mean, min, max, standard deviation, p95.
- `POST /api/benchmark/export` returns CSV.
- `GET /api/benchmark/suite` returns the fixed seven-query suite.
- `GET /api/benchmark/results.csv` serves the generated CSV.
- One unmeasured warm-up run is optional; cache clearing is recorded.

### Tests

- **101 pytest tests pass** against the real database and real model.
- 65 test functions, with parametrisation producing 101 collected tests.
- Coverage includes dataset integrity, parser behaviour, all seven methods, index
  evidence, scope gate, cache hit/miss/TTL/LRU, benchmark statistics, CSV export,
  validation errors, SQL injection safety, and product detail.

### Verification already performed

- All seven indexes are valid and ready.
- Representative plans use the primary key, price/category/rating B-trees, brand hash,
  composite index, and HNSW index.
- Out-of-scope queries return zero results and zero DB time.
- Repeated searches return identical rows.
- The analysis page groups multiple methods under one query ID and separates different
  queries.

---

## 9. Security, reliability, and honest limitations

### Security

- All user values are bound as `%s` parameters.
- SQL text is built only from fixed fragments and column names.
- Input is validated for type, length, method, and limit.
- User input never appears in the SQL string; it appears only in `params`.
- Tests include an injection payload and confirm the table is not dropped.

### Reliability

- psycopg connection pool (`min_size=1`, `max_size=10`).
- Thread-safe cache with TTL and LRU.
- Startup warm-up loads the model and touches each index once.
- JSON error responses for validation, 404, 405, and 500.
- Health endpoint reports database, pgvector, dataset, index, and model status.

### Honest limitations (say these before the professor asks)

- HNSW is approximate; recall is not measured against exact nearest neighbours.
- `ILIKE '%keyword%'` cannot use a B-tree; a trigram/GIN index would be the right tool
  for that workload.
- The planner may choose a different index than the method's "expected" index; the
  actual plan is reported, and that is intentional.
- The dataset is synthetic, not real retail inventory.
- The cache is per-process, not shared across workers.
- Cold-start PostgreSQL behaviour is not benchmarked; warm-up is documented.
- The analysis history is stored only in the browser, not in a server database.

---

## 10. Live demo script (about 8–10 minutes)

Before the demo:

```bash
cd /Users/ankurdhanraj/Desktop/dbms_2
bash scripts/start_postgres.sh      # if PostgreSQL is not running
source .venv/bin/activate
python run.py
```

Open **http://127.0.0.1:5001**.

### Demo sequence

1. **Show the health state.** Point at the green "PostgreSQL online" pill. Optionally
   open `http://127.0.0.1:5001/api/health` and point to `product_count: 100000`,
   `embedded_count: 100000`, `pgvector_version: 0.8.7`, and the index list.
2. **Full Table Scan.** Enter `black laptop under 80000`, choose **Full Table Scan**,
   Top 5, click Search. Point out the DB execution time and the query ID.
3. **Same query, B+ Tree.** Do not change the query. Choose **B+ Tree** and Search.
   Point out that the query ID is the same and the time is much lower.
4. **Same query, Composite Index.** Choose **Composite Index** and Search. Point out
   that this query has category, price, and colour, which fits the composite index.
5. **Same query, HNSW and Hybrid.** Choose each and Search. Explain that these use the
   embedding and are semantic, so they are not directly comparable to relational
   methods; their DB time excludes embedding time.
6. **Open the analysis.** Click **View Q-XXXXXX analysis** or the Analysis nav link.
   Show the bar chart: only the methods you ran appear. Show the table.
7. **Change the query.** Go back to Search (the previous query is prefilled), change it
   to `Samsung smartphone`, choose **Hash Index**, and Search. Open Analysis again.
   Point out that this is a second query ID and a second graph.
8. **Click between queries.** In the "All query analyses" list, click the first query
   ID and then the second. The graph switches without a page reload.
9. **Out-of-scope example.** Search `flying car`. Show the notice and zero products.
   Explain that no SQL was executed (`db_execution_ms = 0`).
10. **Close with honesty.** Mention the plan inspection, the 101 tests, and the known
    limitations.

### If something goes wrong

- **Database offline:** run `bash scripts/start_postgres.sh`, wait, refresh.
- **First semantic search slow:** the model warm-up may still be running; wait a few
  seconds and repeat.
- **Analysis graph empty:** run at least one in-scope search in this browser profile;
  the store is browser-local.
- **Wrong query ID selection:** open `/analysis?q=Q-XXXXXX` with the ID shown on the
  search result.
- **Server not running:** `.venv/bin/python run.py` from the project folder.

---

## 11. Work division for three team members

> Replace the placeholder names with your real names. This division follows the
> actual files and responsibilities in the repository. Adjust if your real
> contributions differed, but keep the story consistent.

### 11.1 Ownership table

| Area | Owner | Key files | What they explain | Demo segment | Likely viva focus |
|---|---|---|---|---|---|
| Dataset, schema, indexes, import pipeline | **Member 1 — Data & Database Engineer** | `synthetic_products_100000.csv`, `scripts/validate_dataset.py`, `scripts/schema.sql`, `scripts/init_db.py`, `scripts/import_data.py`, `scripts/generate_embeddings.py`, `app/db.py` | 100k dataset, validation, table design, seven indexes, pgvector embeddings, index sizes and validity | Health/index evidence; explain the index inventory | B-tree vs hash, composite leading column, HNSW parameters, why 100k, data quality |
| Flask API, parser, scope gate, seven methods, timing, cache, benchmark | **Member 2 — Backend & Search Engineer** | `app/__init__.py`, `app/routes.py`, `app/query_parser.py`, `app/search/*`, `app/embeddings.py`, `app/cache.py`, `app/plan.py`, `app/benchmark.py`, `app/config.py` | Request lifecycle, parser, scope gate, parameterised SQL, all seven methods, timing fairness, EXPLAIN, cache | Run the seven methods; explain each result and warning | How SQL is built, why no fallback, how DB time is measured, iterative HNSW, cache key/TTL |
| Search UI, analysis dashboard, query IDs, tests, docs | **Member 3 — Frontend, Analysis & QA Engineer** | `templates/index.html`, `templates/analysis.html`, `static/js/app.js`, `static/js/analysis.js`, `static/css/style.css`, `tests/`, `README.md`, `docs/` | UI flow, query-ID grouping, localStorage, Chart.js, clickable query list, out-of-scope notice, test strategy | Same-query method comparison; click between query graphs; out-of-scope demo | How query ID is generated, how grouping works, why localStorage, how tests prove correctness, accessibility/security |

**Approximate effort split:** 33% / 34% / 33%. Every member also participates in
integration, rehearsal, and the final Q&A.

### 11.2 Speaking order and timing (12-minute version)

| Time | Speaker | Content |
|---|---|---|
| 0:00–1:30 | Member 1 | Problem statement, project goal, dataset overview |
| 1:30–3:30 | Member 1 | Schema and index design; why each index exists; index sizes/validity |
| 3:30–5:00 | Member 2 | Architecture and end-to-end request lifecycle |
| 5:00–7:00 | Member 2 | Parser and scope gate; parameterised SQL and timing methodology |
| 7:00–8:30 | Member 2 | Seven methods and the hybrid iterative-scan fix |
| 8:30–10:30 | Member 3 | Live demo: same query across methods, query-specific analysis, clickable list |
| 10:30–11:30 | Member 3 | Testing, validation, security, honest limitations |
| 11:30–12:00 | All | Conclusion and Q&A handoff |

If the presentation is only 8 minutes, shorten the index inventory and demo to one
query with three methods plus one different query.

### 11.3 What each member must be ready to answer

**Member 1 — Data & Database**

- Why 100,000 rows and why synthetic data?
- How did you validate the dataset?
- Why a B-tree on price/category/rating?
- Why a hash index on brand, and what can it not do?
- Why is category first in the composite index?
- What do `m=16` and `ef_construction=64` mean?
- How do you know the indexes are valid and used?
- What is the size cost of the HNSW index?

**Member 2 — Backend & Search**

- Walk me through one request from browser to database and back.
- How does the parser avoid inventing filters?
- How does the scope gate reject `flying car` without a DB query?
- Why is there no keyword-relaxation fallback?
- How exactly is `db_execution_ms` measured?
- Why is `include_plan` false for interactive searches?
- Why did hybrid initially return zero results, and how did you fix it?
- What is the difference between the cache and an index?
- How do you prevent SQL injection?
- Why does the B+ Tree method sometimes use the composite index?

**Member 3 — Frontend, Analysis & QA**

- How is the query ID generated and why is it stable?
- How does the same query with a new method update the same graph?
- How does a different query create a new graph?
- Where is the analysis stored, and what happens if the browser storage is cleared?
- How does clicking a query card switch the graph?
- What does the graph deliberately exclude, and why?
- How do you show out-of-scope queries in the UI?
- How do the 101 tests prove the system works?
- What are the main limitations and future improvements?
- How did you ensure user text is escaped in the UI?

### 11.4 Shared responsibilities (everyone)

- Be able to start the app and run the demo.
- Know the architecture diagram and the seven method names.
- Know the three headline numbers: 100,000 products, 384 dimensions, 7 indexes.
- Know the headline result: index methods are much faster than the forced full scan
  on selective queries, but not every query benefits.
- Know the honest limitations.
- Never claim a specific index was used without the plan evidence.

---

## 12. Twelve-slide outline

1. **Title** — project name, team names, one-line goal.
2. **Problem & motivation** — product search at scale; why indexes matter; why compare?
3. **Dataset** — 100,000 products, 10 categories, 384-d embeddings; validation.
4. **Schema & indexes** — table + seven-index inventory with sizes.
5. **Architecture** — browser → Flask → parser/scope → search → PostgreSQL → response.
6. **Request lifecycle** — the ten steps; where time is measured.
7. **Relational methods** — full scan, B+ tree, hash, composite; leading-column rule.
8. **Vector & hybrid methods** — embeddings, HNSW, cosine, iterative scan, cache.
9. **Correctness & fairness** — parameterised SQL, scope gate, one query per search,
   plan evidence, warm-up.
10. **Query-specific analysis** — query ID, same-query method bars, different-query
    graphs, clickable list.
11. **Results & testing** — representative timings, 101 tests, index validity.
12. **Limitations & conclusion** — what we learned, what we would improve.

---

## 13. Viva / professor Q&A bank

Use short answers first, then add detail if asked.

**Q1. Why did you build seven methods instead of just using the fastest index?**  
Because the goal is comparative DBMS education. Each method exposes a different access
path and a different trade-off. The application never auto-selects a method.

**Q2. Is your "B+ Tree" really a B+ tree?**  
PostgreSQL's default index is a B-tree. The project uses the label B+ Tree for the
course concept and explicitly explains that PostgreSQL implements the B-tree family.
The index definitions and plans are shown as evidence.

**Q3. Why does the B+ Tree method sometimes use the composite index?**  
Because the planner is free to choose any suitable index in the schema. The method
labels describe the intended index family, not a restriction. We report the actual
plan instead of hiding that behaviour.

**Q4. What is the difference between the hash and B-tree methods?**  
Hash supports equality only (`brand = 'Samsung'`); it cannot help with ranges or
ordering. B-trees support equality, ranges, and ordered retrieval. A hash index is
smaller and fast for exact matches, but limited.

**Q5. Why is category the first column of the composite index?**  
Because queries frequently constrain category, and a multicolumn B-tree is usable when
the leading column is constrained. Without category, the index is reported as not
applicable.

**Q6. Why doesn't the composite index help with colour after a price range?**  
Once a range predicate is applied to `price_inr`, later columns such as `color` are
generally used as filters rather than tight index bounds. Column order is a deliberate
trade-off.

**Q7. How does HNSW work?**  
It builds a multi-layer proximity graph. Search starts at the top layer and greedily
moves toward the query vector, then descends. `m` controls links per node,
`ef_construction` controls build quality, and `ef_search` controls query-time
candidates. It is approximate.

**Q8. Why did hybrid search return zero results at first?**  
HNSW filters after the graph scan. A selective structured filter could reject all
nearest `ef_search` candidates. We enabled `hnsw.iterative_scan = relaxed_order` so
pgvector continues until enough filtered rows are found.

**Q9. Why not always use HNSW?**  
HNSW is approximate and does not enforce structured filters. For exact category/price
queries, a relational index is often cheaper and exact. Hybrid combines both.

**Q10. Why is embedding time excluded from the graph?**  
The graph compares database index performance. Embedding is a fixed model cost outside
PostgreSQL. The API reports `embedding_ms` separately so the full end-to-end cost is
still available.

**Q11. Why are repeated timings stable now?**  
One search executes one SQL statement; plan capture is disabled for interactive
searches; the model and indexes are warmed at startup. The cached method is the
intentional exception.

**Q12. What is the cache, and is it an index?**  
It is an in-process TTL + LRU cache of result sets, keyed by method/query/limit. It is
not a database index. A miss runs hybrid search; a hit returns stored results with
zero DB time. It is not shared across worker processes.

**Q13. How do you prove an index was actually used?**  
We request `EXPLAIN (ANALYZE, BUFFERS, VERBOSE, FORMAT JSON)` through the API/tests and
report `indexes_used`, node types, rows, and buffers. We also verify `pg_index`
validity/readiness and the `pg_indexes` definitions.

**Q14. How do you prevent SQL injection?**  
Every user value is a `%s` parameter. SQL text is assembled only from fixed fragments
and column names. Tests send an injection payload and confirm the table survives and
the payload never appears in SQL text.

**Q15. Why do out-of-scope queries return zero instead of nearest neighbours?**  
A vector search always returns neighbours, even for nonsense. The scope gate checks
category/brand or word-boundary keyword matches first. Out-of-scope queries return zero
without executing SQL. A similarity floor is a second safety net.

**Q16. How did you validate the dataset?**  
`scripts/validate_dataset.py` checks exact row count, unique IDs, 10 × 10,000 category
distribution, missing values, numeric ranges, duplicates, and ID format. Results are in
`data/dataset_validation.json` and `docs/validation_report.md`.

**Q17. What are the limitations?**  
Synthetic data, approximate HNSW recall, no trigram/GIN index for leading-wildcard
text, browser-local analysis history, per-process cache, warm (not cold) PostgreSQL
measurements.

**Q18. What would you improve next?**  
Add a GIN/trigram index for keyword search, measure exact HNSW recall, test concurrent
load, support real product images, move analysis history to a server-side store, and
add a larger real-world dataset.

**Q19. How is the query ID generated?**  
FNV-1a hash of the normalised query plus the result limit, formatted as `Q-XXXXXX`.
The same query and limit always produce the same ID in that browser.

**Q20. Why does changing the query create a new graph?**  
Because comparing methods only makes sense for the same information need. A different
query has different selectivity and filters, so its timings belong in a separate
analysis.

---

## 14. Rehearsal checklist

- [ ] Replace the placeholder names with the real team names.
- [ ] Each member can start PostgreSQL and Flask from a terminal.
- [ ] Each member can explain the architecture diagram without reading.
- [ ] Each member can name all seven methods and their index families.
- [ ] Each member can run the demo sequence once end-to-end.
- [ ] The browser profile used for the demo has at least two saved queries with
      multiple methods each.
- [ ] Clear old analysis data before the final rehearsal, then rebuild a clean demo.
- [ ] Check that `/` and `/analysis` load, and that `flying car` returns zero.
- [ ] Keep a backup of the key numbers: 100,000 products, 100,000 embeddings,
      384 dimensions, 7 indexes, 101 tests.
- [ ] Decide who answers which category of question; everyone can hand off cleanly.
- [ ] Do not use the old screenshots `03_benchmark_dashboard.png` or
      `04_technical_details.png`; those UI sections were intentionally removed.

---

## 15. Commands and URLs

```bash
cd /Users/ankurdhanraj/Desktop/dbms_2
bash scripts/start_postgres.sh
source .venv/bin/activate
python run.py
```

| Page / endpoint | URL |
|---|---|
| Search page | http://127.0.0.1:5001/ |
| Analysis page | http://127.0.0.1:5001/analysis |
| Query-specific analysis | http://127.0.0.1:5001/analysis?q=Q-XXXXXX |
| Health / index evidence | http://127.0.0.1:5001/api/health |
| Method metadata | http://127.0.0.1:5001/api/methods |
| Search API | `POST http://127.0.0.1:5001/api/search` |

Example API call:

```bash
curl -X POST http://127.0.0.1:5001/api/search \
  -H 'Content-Type: application/json' \
  -d '{"query":"black laptop under 80000","method":"composite_btree","limit":5,"include_plan":false}'
```

Run the tests:

```bash
.venv/bin/python -m pytest -q
```

Expected: **101 passed**.

---

## 16. From idea to final project — the complete story

This section is the narrative you use when the professor wants to understand the
project as a piece of engineering, not just a demo. It covers why the project exists,
what we promised, what we deliberately excluded, why each technology was chosen, how
the work was built in phases, and which problems changed the design.

### 16.1 The original problem

Database courses teach indexes through diagrams: a B-tree splits, a hash bucket points
to a row, a planner picks an access path. What students rarely see is the same query
executed through several access paths on a real dataset, with the real planner, real
timings, and real index sizes. Textbook examples also hide the awkward cases: an index
that exists but is not used, a hash index that cannot answer a range query, a vector
index that returns nearest neighbours for nonsense input, or a composite index that is
useless without its leading column.

The idea was therefore not “build an online shop”. It was:

> Build a realistic product catalogue, expose several fundamentally different
> retrieval mechanisms as separate user choices, and make PostgreSQL show what it
> actually did and how long it actually took.

That framing keeps the project a **DBMS project** rather than a web-development
project. The UI exists to make database behaviour observable.

### 16.2 The three questions the project answers

1. **How much does each access path cost for the same information need?**
   The same query is run through a forced sequential scan, a B+ tree method, a hash
   method, a composite index, HNSW, hybrid search, and a cache.
2. **Does the database do what the method name suggests?**
   Not always. The B+ Tree method may use the composite index; the hash method may
   report “not applicable”; the hybrid method may use the HNSW index, a relational
   index, or both. The project reports the actual `EXPLAIN` plan instead of hiding
   this.
3. **Can semantic similarity be combined with hard structured filters without
   returning random or empty results?**
   Yes, but it needs a scope gate, a similarity floor, and pgvector iterative scanning.

### 16.3 Goals and non-goals

**Goals**

- A real PostgreSQL database with 100,000 products and 100,000 embeddings.
- Seven separately selectable retrieval methods, each implemented in its own module.
- Real measured timings, not a hard-coded results table.
- A parser that converts natural language into safe, parameterised SQL.
- Evidence for index use: `EXPLAIN (ANALYZE, BUFFERS, VERBOSE, FORMAT JSON)`,
  `pg_index` validity, and index sizes.
- A query-specific analysis dashboard: one graph per query, one bar per method tried.
- A reproducible dataset and a test suite that runs against the real database.
- Completely free and offline after the model download.

**Non-goals (say these clearly)**

- It is not a production e-commerce site: no payments, accounts, orders, or admin.
- It is not an image search engine; `image_key` and `image_prompt` are reserved fields.
- It is not an LLM chatbot; the parser is deterministic and rule-based.
- It does not benchmark cold-start PostgreSQL or concurrent multi-user load.
- It does not claim exact nearest-neighbour recall from HNSW.
- It does not share the cache or analysis history across browsers or processes.

### 16.4 Requirements

| Type | Requirement | How it is met |
|---|---|---|
| Functional | Accept a natural-language product query | `query_parser.parse_query()` |
| Functional | Let the user choose one of seven methods manually | `method` field + method dropdown |
| Functional | Return product rows with a limit of 5 or 10 | Parameterised `LIMIT`, validated input |
| Functional | Show parsed filters | `parsed_filters` in the response + UI strip |
| Functional | Show database execution time | `db_execution_ms` measured with `perf_counter` |
| Functional | Show which indexes were used | `technical.indexes_used` from `EXPLAIN` |
| Functional | Group measurements per query | Stable query ID + `localStorage` store |
| Functional | Let the user reopen a saved query graph | Clickable list + `/analysis?q=ID` deep link |
| Functional | Reject unrelated queries without SQL | Scope gate returns `out_of_scope` |
| Functional | Report cache hit/miss | `cache.status` + cache statistics endpoint |
| Non-functional | Prevent SQL injection | Every value bound as `%s` |
| Non-functional | Keep timings fair | One statement per interactive search; no plan capture |
| Non-functional | Be reproducible | Fixed CSV, validation report, fixed benchmark suite |
| Non-functional | Be verifiable | 101 pytest tests against the real database |
| Non-functional | Run offline and free | Local model, local PostgreSQL, no paid APIs |

### 16.5 Design decisions and the alternatives we rejected

| Decision | Alternative considered | Why we chose this |
|---|---|---|
| PostgreSQL | SQLite, MySQL, MongoDB | PostgreSQL has B-tree, hash, multicolumn indexes, `EXPLAIN ANALYZE`, and the pgvector extension in one engine. SQLite lacks hash indexes and server-side vector search; MongoDB would hide the relational index comparison. |
| pgvector | FAISS, Chroma, Pinecone | pgvector keeps vectors **inside the same database and the same query**, so hybrid filtering and vector ordering can be one SQL statement. FAISS/Chroma would add a second store and break transactional consistency; Pinecone is paid and online. |
| Local `all-MiniLM-L6-v2` | OpenAI/Cohere embeddings | Free, offline, deterministic, 384 dimensions, fast on CPU. No API key or per-query cost during a live demo. |
| Flask | Django, FastAPI, Node | The project is a small API plus two pages. Flask keeps the request lifecycle visible and the dependency set small. Django would add ORM/admin machinery that hides the SQL we want to teach. |
| Rule-based parser | LLM function calling | Deterministic, testable, explainable, and free. An LLM could invent filters or vary between runs, which would ruin a benchmark. |
| Synthetic 100,000-row dataset | Real scraped catalogue | Controlled category distribution, known price/rating ranges, no licensing or privacy issues, and every student benchmarks the same workload. Real data would make results non-reproducible. |
| Seven manual methods | Auto-select the “best” method | The pedagogical point is comparison. Auto-selection would hide the trade-offs and make the analysis page meaningless. |
| Single `products` table | Fully normalised schema | The benchmark is about access paths, not joins. One wide table keeps the comparison clean and keeps the HNSW index meaningful. Normalisation would add join cost that confounds the result. |
| `localStorage` for analysis | Server-side analysis table | No login or user accounts are needed; the history is a personal demo artefact. It also avoids writing benchmark data into the production table. |
| In-process TTL/LRU cache | Redis / Memcached | The cache method is about the **concept** of application caching. Redis would add an external service and network latency that obscures the lesson. |
| `include_plan: false` for interactive searches | Always run `EXPLAIN ANALYZE` | `EXPLAIN ANALYZE` executes the query again, doubling the measured work. Plans are still available on demand through the API and tests. |
| Warm-up at startup | Measure cold starts | A cold model load and cold index pages would dominate the first demo query. Warm-up makes repeated interactive timings stable and honest about being warm measurements. |

### 16.6 Development phases (logical build order)

The project was built in layers. If your report has dates, attach them to these
phases; the order is what matters.

**Phase 0 — Idea and scope.** Define the comparison, choose PostgreSQL + pgvector,
decide that the user selects the method manually, and decide that all timings must be
real.

**Phase 1 — Dataset.** Generate/obtain 100,000 synthetic products across 10 categories,
45 brands, 39 use cases, seven colours, realistic prices and ratings. Write
`scripts/validate_dataset.py` to check row count, unique IDs, category distribution,
missing values, numeric ranges, duplicates, and ID format. The original CSV is never
modified. Output: `data/dataset_validation.json` and `docs/validation_report.md`.

**Phase 2 — Schema and relational indexes.** Create `products`, the `vector(384)`
column, `CHECK` constraints, three single-column B-trees, one hash index, and the
multicolumn `(category, price_inr, color)` B-tree. Run `ANALYZE`. Output:
`scripts/schema.sql`.

**Phase 3 — Import.** Bulk-load with `COPY` through `scripts/import_data.py`, refusing
to import if validation fails. Embeddings are loaded separately so index construction
can be measured and retried.

**Phase 4 — Embeddings and HNSW.** Encode `name | category | brand | use_case |
specifications | description | tags | colour` with `all-MiniLM-L6-v2`, L2-normalise,
store as `vector(384)`, then build the HNSW index with `m=16`,
`ef_construction=64`, and `vector_cosine_ops`. Output:
`scripts/generate_embeddings.py`.

**Phase 5 — Backend search.** Build the parser lexicon, the scope gate, the shared SQL
builder, the timing wrapper, the seven method modules, the dispatcher, warnings, and
the API. Add plan parsing and index evidence. Output: `app/`.

**Phase 6 — Search UI.** Build the query box, method dropdown, limit selector, result
cards, metric cards, parsed-filter strip, warnings, and query-ID link. Output:
`templates/index.html`, `static/js/app.js`, `static/css/style.css`.

**Phase 7 — Query-specific analysis.** Replace the global “latest per method” view with
a per-query store. Add stable query IDs, the saved-query list, clickable switching,
deep links, and last-search prefill. Output: `templates/analysis.html`,
`static/js/analysis.js`.

**Phase 8 — Verification and documentation.** Write 65 test functions (101 collected
tests), run the fixed benchmark suite, export CSV/JSON, and write the README plus the
`docs/` set. Output: `tests/`, `docs/`, `data/benchmark_results.json`.

### 16.7 How the design changed during development

These changes are worth mentioning because they show engineering judgement, not a
straight-line build.

1. **The B+ Tree method was removed, then restored.** At one point the single-column
   B-trees were only used implicitly by the planner. After review, we restored an
   explicit `btree` method so the course concept is directly selectable. This brought
   the count from six methods back to seven.
2. **The analysis changed from “latest per method” to “per query”.** The first version
   stored one latest measurement per method globally. That made it impossible to
   compare methods on the same query or to keep two queries separate. We replaced it
   with a store keyed by a stable query ID.
3. **The benchmark dashboard and technical SQL panel were removed from the UI.** They
   made the demo feel like a developer tool. The benchmark API remains for academic
   measurement, and plans remain available through the API and tests.
4. **Hybrid search needed iterative scanning.** With a selective filter, the nearest
   HNSW candidates could all fail the `WHERE` clause, producing zero rows. Setting
   `hnsw.iterative_scan = relaxed_order` fixed it.
5. **Nonsense queries needed a scope gate.** A vector index always returns neighbours,
   so `flying car` returned unrelated products. The scope gate rejects such queries
   before any SQL runs.
6. **Interactive timings needed one statement, not two.** Capturing a plan with
   `EXPLAIN ANALYZE` re-executes the query. Interactive searches now send
   `include_plan: false`.
7. **The first search was slow.** The model and index pages were cold. Startup warm-up
   now loads the model and touches every method once, then clears the cache so the
   cached method still shows a real first miss.
8. **Returning to Search lost the query.** Comparing methods required retyping the same
   query. The last query, method, and limit are now stored in `localStorage` and
   prefilled.

### 16.8 Problems found and how they were fixed

| Symptom | Root cause | Fix |
|---|---|---|
| Hybrid returned 0 rows on selective filters | HNSW filters after the graph scan; all `ef_search` candidates were rejected | `SET LOCAL hnsw.iterative_scan = relaxed_order` |
| `flying car` returned five random products | Vector search always returns nearest neighbours | Scope gate before SQL + cosine similarity floor `0.30` |
| Timing looked inflated | `EXPLAIN ANALYZE` executed the query a second time | `include_plan: false` for interactive searches; report `plan_capture_ms` separately |
| First search took seconds longer | Cold Sentence Transformers model and cold index pages | Startup warm-up thread; cache cleared afterwards |
| A new method overwrote the previous method's bar | Analysis keyed only by method | Store keyed by query ID, then method inside the query |
| Two different queries shared one graph | No query identity | FNV-1a hash of normalised query + limit → `Q-XXXXXX` |
| Hash method appeared to use an index when no brand existed | Planner used a different index | `hash_index_applicable` flag + user warning |
| Composite index was not chosen even with a category filter | Result ordering forced a sort | Order by `price_inr, color, product_id` so the index serves filtering and ordering |
| SQL injection was a risk | String-built SQL | All values as `%s`; only fixed fragments in SQL text |
| Analysis history looked stale after a redesign | Old `localStorage` key | Versioned key `dbms2.analysis.queries.v1` + clear button |
| Demo UI was cluttered | Benchmark and SQL panels | Removed from UI; API retained for evidence |

### 16.9 What is genuinely our work

The project uses open-source libraries, but the following are original work:

- The dataset design and validation rules.
- The schema and the choice/column order of every index.
- The rule-based parser, synonym maps, and scope gate.
- The shared SQL builder and the seven method implementations.
- The timing methodology and the decision to separate plan capture, embedding, parse,
  and database time.
- The query-ID scheme and the query-scoped analysis dashboard.
- The cache key/TTL/LRU behaviour and statistics.
- The 65 test functions and the documentation set.

PostgreSQL, pgvector, Sentence Transformers, Flask, psycopg, Chart.js, and pandas are
dependencies, not our code. Being precise about this is a strength in a viva.

### 16.10 Definition of “done” (the final state)

- 100,000 products, 100,000 embeddings, 10 categories, 45 brands.
- Seven indexes valid and ready, including a 191 MB HNSW index.
- Seven selectable methods, each with its own module.
- Real `db_execution_ms`, real plans, and honest warnings.
- Query-specific analysis with stable IDs, clickable history, and deep links.
- 101 passing tests against the real database and model.
- A reproducible setup, a fixed benchmark suite, and complete documentation.

---

## 17. Repository map and setup from scratch

### 17.1 Repository map

```text
dbms_2/
├── app/
│   ├── __init__.py              # Flask factory, warm-up, error handlers, security headers
│   ├── config.py                # DATABASE_URL, model, cache, HNSW, limits, ports
│   ├── db.py                    # psycopg connection pool + fetch helpers
│   ├── routes.py                # pages + /api/search, /api/health, /api/methods, benchmark, cache
│   ├── query_parser.py          # lexicon, synonyms, price parsing, scope gate + scope cache
│   ├── embeddings.py            # local model, encode_query/encode_texts, product_embedding_text
│   ├── cache.py                 # thread-safe TTL + LRU cache and statistics
│   ├── plan.py                  # EXPLAIN JSON parser → indexes, nodes, rows, buffers
│   ├── benchmark.py             # repetitions, statistics, CSV export
│   └── search/
│       ├── __init__.py          # registry, validation, dispatch, response, warnings
│       ├── base.py              # structured_conditions, relational_sql, execute_sql, timing
│       ├── full_scan.py         # Method 1
│       ├── btree.py             # Method 2
│       ├── hash_index.py        # Method 3
│       ├── composite_btree.py   # Method 4
│       ├── hnsw.py              # Method 5
│       ├── hybrid.py            # Method 6
│       └── cached.py            # Method 7
├── templates/
│   ├── index.html               # search page
│   └── analysis.html            # query-specific analysis page
├── static/
│   ├── css/style.css
│   ├── js/app.js                # search flow, query ID, localStorage
│   ├── js/analysis.js           # per-query chart, table, clickable list
│   └── vendor/chart.umd.min.js
├── scripts/
│   ├── validate_dataset.py      # schema/quality checks, writes data/dataset_validation.json
│   ├── schema.sql               # table + all indexes
│   ├── init_db.py               # creates schema, runs ANALYZE
│   ├── import_data.py           # validates then COPYs 100,000 rows
│   ├── generate_embeddings.py   # embeddings + HNSW build
│   ├── run_benchmarks.py        # fixed suite → JSON/CSV
│   ├── start_postgres.sh        # local PostgreSQL 19 on port 5433
│   └── stop_postgres.sh
├── tests/                       # 65 functions / 101 collected tests
├── data/
│   ├── dataset_validation.json
│   └── benchmark_results.json
├── docs/                        # architecture, API, methods, testing, benchmarks, this guide
├── project_documentation/       # original PDFs (do not modify)
├── synthetic_products_100000.csv
├── requirements.txt
├── pytest.ini
├── .env.example
└── run.py
```

### 17.2 From-scratch setup (exact order)

Requirements: Python 3.11/3.12, PostgreSQL 16+ with pgvector, and about 1 GB of free
space for the table, embeddings, and HNSW index.

```bash
cd /Users/ankurdhanraj/Desktop/dbms_2

# 1. Python environment
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. Configuration
cp .env.example .env          # edit DATABASE_URL if your port differs

# 3. PostgreSQL (Postgres.app on macOS bundles pgvector)
bash scripts/start_postgres.sh

# 4. Validate the CSV without modifying it
python scripts/validate_dataset.py

# 5. Create schema, pgvector extension, and relational indexes
python scripts/init_db.py

# 6. Bulk import 100,000 rows with COPY
python scripts/import_data.py

# 7. Generate 100,000 embeddings and build HNSW
#    (first run downloads all-MiniLM-L6-v2, ~90 MB, then caches it)
python scripts/generate_embeddings.py

# 8. Optional: fixed benchmark suite
python scripts/run_benchmarks.py --repetitions 5 --limit 10

# 9. Run the app
python run.py
```

Open **http://127.0.0.1:5001**.

### 17.3 Configuration variables

| Variable | Default | Meaning |
|---|---|---|
| `DATABASE_URL` | `postgresql://localhost:5433/product_search` | PostgreSQL connection string |
| `EMBEDDING_MODEL` | `sentence-transformers/all-MiniLM-L6-v2` | Local embedding model |
| `EMBEDDING_DIM` | `384` | Must match the model and `vector(384)` |
| `CACHE_TTL_SECONDS` | `300` | Cache entry lifetime |
| `CACHE_MAX_ENTRIES` | `512` | LRU capacity |
| `HNSW_EF_SEARCH` | `100` | Query-time HNSW candidate list |
| `HNSW_MIN_SIMILARITY` | `0.30` | Cosine similarity floor |
| `WARM_UP_ON_START` | `1` | Load model/touch indexes at startup |
| `FLASK_HOST` / `FLASK_PORT` | `127.0.0.1` / `5001` | Web server binding |
| `FLASK_DEBUG` | `0` | Debug mode (keep off for timing) |

### 17.4 How to verify the installation in one minute

```bash
# Health: database, pgvector, row counts, index list
curl -s http://127.0.0.1:5001/api/health | python -m json.tool

# Seven methods
curl -s http://127.0.0.1:5001/api/methods | python -m json.tool

# One real search with a plan
curl -s -X POST http://127.0.0.1:5001/api/search \
  -H 'Content-Type: application/json' \
  -d '{"query":"black laptop under 80000","method":"composite_btree","limit":5,"include_plan":true}' \
  | python -m json.tool

# Index validity and sizes directly in PostgreSQL
psql -h localhost -p 5433 -d product_search -c "
SELECT c.relname, am.amname, pg_size_pretty(pg_relation_size(c.oid)) AS size,
       i.indisvalid, i.indisready
FROM pg_index i
JOIN pg_class c ON c.oid = i.indexrelid
JOIN pg_class t ON t.oid = i.indrelid
JOIN pg_am am ON am.oid = c.relam
WHERE t.relname = 'products'
ORDER BY c.relname;"

# Tests
.venv/bin/python -m pytest -q
```

Expected: healthy database, seven methods, real results with an index plan, seven
valid indexes, and `101 passed`.

### 17.5 Rebuilding and troubleshooting

- **Rebuild the database:** `python scripts/init_db.py` drops and recreates the table,
  so rerun `import_data.py`, `generate_embeddings.py`, and optionally
  `run_benchmarks.py`.
- **PostgreSQL offline:** `bash scripts/start_postgres.sh`; check `.pglog/postgres.log`.
- **Port 5001 busy:** `lsof -tiTCP:5001 -sTCP:LISTEN | xargs kill`, then `python run.py`.
- **Model download blocked:** the model is cached under the Hugging Face cache; the app
  runs offline after the first successful download.
- **Analysis graph empty:** the store is browser-local; run at least one in-scope
  search in the browser profile used for the demo.
- **Wrong query card:** open `/analysis?q=Q-XXXXXX` with the ID shown on the search
  result.
- **Do not modify** anything under `project_documentation/`; those PDFs are original
  submissions.

---

## 18. Glossary (every term used in the presentation)

| Term | Meaning in this project |
|---|---|
| **Access path** | The way PostgreSQL reads rows: sequential scan, index scan, bitmap scan, etc. |
| **Sequential scan (Seq Scan)** | Reads every row in the table; used as the full-scan baseline. |
| **Index scan** | Walks an index and fetches matching table rows. |
| **Index-only scan** | Answers from the index without visiting the table when all needed columns are in the index. |
| **Bitmap scan** | Builds a bitmap of matching row locations, then reads the table in physical order. |
| **B-tree** | Balanced tree index supporting equality, ranges, and ordering. PostgreSQL's default index type. |
| **B+ tree** | The course concept of a B-tree variant that stores all keys in leaf nodes and links leaves for range scans. This project uses PostgreSQL B-tree indexes and explains the naming. |
| **Hash index** | Index that maps a key hash to row locations; equality only, no ranges or ordering. |
| **Composite (multicolumn) index** | An index on several columns in a fixed order, e.g. `(category, price_inr, color)`. |
| **Leading-column rule** | A composite index is generally usable only when the first column is constrained. |
| **Selectivity** | How many rows a predicate keeps; a highly selective filter keeps few rows. |
| **Cardinality** | Number of distinct values in a column, or the planner's estimated row count. |
| **Planner / optimizer** | PostgreSQL component that chooses the access path and join order. |
| **`EXPLAIN`** | Shows the plan without running the query. |
| **`EXPLAIN ANALYZE`** | Runs the query and shows the actual plan, row counts, and timings. |
| **Buffers** | Shared/read block counts reported by `EXPLAIN (BUFFERS)`, showing cache behaviour. |
| **Plan capture** | Our separate `EXPLAIN ANALYZE` run used for evidence; excluded from `db_execution_ms`. |
| **Parameterised query** | SQL with `%s` placeholders and values sent separately; prevents injection. |
| **Query ID** | Stable browser-side identifier `Q-XXXXXX` for a normalised query plus limit. |
| **FNV-1a** | Fast non-cryptographic hash used to derive the query ID. |
| **Embedding** | A numeric vector representing text meaning; here 384 dimensions. |
| **Cosine distance / similarity** | `<=>` returns distance; `1 - distance` is similarity. |
| **ANN / nearest neighbour** | Approximate nearest-neighbour search over vectors. |
| **HNSW** | Hierarchical Navigable Small World graph index used by pgvector for ANN search. |
| **`m`** | HNSW parameter: number of links per node. |
| **`ef_construction`** | HNSW build-time candidate list; higher means better graph, slower build. |
| **`ef_search`** | HNSW query-time candidate list; higher means better recall, slower query. |
| **Recall** | Fraction of true nearest neighbours found by an approximate index. |
| **Iterative scan** | pgvector mode that keeps scanning until enough rows pass a filter. |
| **Hybrid search** | Structured SQL filters plus semantic vector ordering in one query. |
| **TTL** | Time-to-live; how long a cache entry stays valid. |
| **LRU** | Least-recently-used eviction policy for a bounded cache. |
| **Cache hit / miss** | A hit returns stored results with zero DB work; a miss runs the real query. |
| **Scope gate** | Pre-check that rejects queries unrelated to the catalogue before SQL runs. |
| **Word-boundary match** | Regex match that prevents `pet` from matching `competitive`. |
| **`localStorage`** | Browser key/value storage used for analysis history and last search. |
| **Chart.js** | JavaScript charting library used for the per-query bar chart. |
| **Warm-up** | Startup work that loads the model and touches indexes so demos are stable. |

---

## 19. Delivery plans for different time limits

### 19.1 Three-minute version (elevator demo)

| Time | Content |
|---|---|
| 0:00–0:30 | Problem: indexes are taught abstractly; we make them visible on 100k real rows |
| 0:30–1:00 | Seven methods, manually selected; real timings, real plans |
| 1:00–2:00 | Demo one query: Full Scan → B+ Tree → Composite; open the query's analysis graph |
| 2:00–2:30 | Second query → new query ID and graph; click between them |
| 2:30–3:00 | One honest limitation (HNSW approximate, synthetic data) + 101 tests |

### 19.2 Eight-minute version

| Time | Content | Slides |
|---|---|---|
| 0:00–0:45 | Problem, goal, dataset headline | 1–3 |
| 0:45–1:45 | Schema and seven-index inventory with sizes | 4 |
| 1:45–3:00 | Architecture and request lifecycle | 5–6 |
| 3:00–4:30 | Relational methods and leading-column rule | 7 |
| 4:30–5:30 | HNSW, hybrid iterative scan, cache | 8 |
| 5:30–6:30 | Demo: same query, three methods, analysis graph, second query | 10 |
| 6:30–7:30 | Correctness, 101 tests, limitations | 9, 11, 12 |
| 7:30–8:00 | Conclusion and Q&A handoff | 12 |

### 19.3 Twelve-minute version

Use the speaking order in section 11.2 and the twelve-slide outline in section 12.
Add the “how the design changed” stories from section 16.7 only if the professor asks
about process; they are strong answers but not needed in the main flow.

### 19.4 Slide-to-section mapping

| Slide | Build it from |
|---|---|
| 1 Title | Section 0 |
| 2 Problem & motivation | Sections 16.1–16.2 |
| 3 Dataset | Section 4.1 |
| 4 Schema & indexes | Sections 4.2–4.3 |
| 5 Architecture | Section 2.2 |
| 6 Request lifecycle | Section 3 |
| 7 Relational methods | Sections 5.1–5.4 |
| 8 Vector, hybrid, cache | Sections 5.5–5.7 |
| 9 Correctness & fairness | Sections 3.1, 8, 9 |
| 10 Query-specific analysis | Section 7 |
| 11 Results & testing | Sections 8, 11 |
| 12 Limitations & conclusion | Section 9 |

---

## 20. Final pre-presentation sanity check

Run this list ten minutes before walking in:

- [ ] `bash scripts/start_postgres.sh` succeeds.
- [ ] `python run.py` is running on port 5001.
- [ ] `/` and `/analysis` both return HTTP 200.
- [ ] `/api/health` shows 100,000 products, 100,000 embeddings, pgvector 0.8.7, and
      seven valid indexes.
- [ ] The demo browser profile has at least two saved queries with multiple methods.
- [ ] `black laptop under 80000` returns results for Full Scan, B+ Tree, and Composite.
- [ ] `flying car` returns the out-of-scope notice and zero products.
- [ ] The analysis graph switches when you click a saved query.
- [ ] `.venv/bin/python -m pytest -q` still reports `101 passed` (run it the day before,
      not during the demo).
- [ ] Every member can name the seven methods and the three headline numbers.
- [ ] You have a backup: screenshots of the analysis graph and the health JSON in case
      the projector or database misbehaves.
