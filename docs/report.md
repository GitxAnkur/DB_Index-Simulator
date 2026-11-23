# Indexed Product Search and Database Performance Benchmarking System

### A Comparative Study of Relational Indexing, Vector Search, and Application Caching on 100,000 Products

**Project type:** DBMS academic project  
**Implementation:** Flask + PostgreSQL 19 + pgvector 0.8.7 + Sentence Transformers + Chart.js  
**Dataset:** 100,000 synthetic products across 10 categories  
**Date:** November 2026

---

## Abstract

This report presents the design, implementation, and empirical evaluation of a
product-search system that compares seven retrieval techniques on a single 100,000-row
dataset. The techniques are: a controlled full table scan, single-column B-tree
indexes, a hash index, a composite B-tree index, HNSW approximate nearest-neighbour
vector search, a hybrid of relational filters and vector ranking, and an
application-level TTL/LRU cache.

The system is a working web application, not a simulation. Every reported timing is
produced by executing parameterised SQL against PostgreSQL; every access path is read
from `EXPLAIN (ANALYZE, BUFFERS, VERBOSE, FORMAT JSON)`. The benchmark runs each
method five times after a warm-up, retains all raw samples, and reports median, mean,
minimum, maximum, standard deviation, and p95.

Across a fixed seven-query suite, the full scan took 9.3–23.8 ms, B-tree variants
0.6–22.1 ms, HNSW 0.55–1.09 ms of database time, and hybrid 0.51–3.45 ms. Cached
searches returned in 0 ms on hits after one real miss. The results show that indexing
is not universally beneficial: B-tree methods were slower than the full scan for
text-heavy `ILIKE` queries, while HNSW was consistently fast but returns different
semantics and incurs query-embedding cost outside the database timing. The report
argues that fair database benchmarking requires controlling cache state, separating
embedding time from database time, reporting actual plans, and disclosing when methods
are not comparable.

---

## 1. Introduction

Product search is a canonical database workload. A user types a short, ambiguous
natural-language phrase — “black laptop under 80000”, “wireless headphones for
travel” — and expects relevant results quickly. Behind that phrase are several
different retrieval problems: equality filtering, range filtering, text matching,
ranking, and sometimes semantic similarity.

Relational databases provide B-tree and hash indexes for structured predicates.
Multicolumn indexes support combinations of predicates, subject to the leading-column
rule. Approximate nearest-neighbour indexes such as HNSW support semantic search over
high-dimensional embeddings. Application caches reduce repeated work for popular
queries. Each technique has different costs, constraints, and result semantics.

This project builds one system that implements all of these approaches behind a
single interface, then measures them under controlled conditions. The goal is not to
declare a winner but to show *when* each technique helps, *why*, and *what evidence*
supports the conclusion.

### 1.1 Objectives

1. Build and validate a 100,000-product dataset.
2. Design a PostgreSQL schema with B-tree, hash, composite, and HNSW indexes.
3. Implement seven separately selectable search methods.
4. Parse natural-language queries into structured filters and keywords.
5. Measure real execution times repeatedly and compute statistics.
6. Capture and display actual query plans.
7. Provide a usable web interface with charts and CSV export.
8. Test the system against the real database.
9. Document methodology, results, and limitations honestly.

### 1.2 Scope

In scope: local execution, synthetic data, CPU embeddings, seven methods, a single
PostgreSQL instance, and a single-page web UI.

Out of scope: production deployment, distributed databases, real retail inventory,
product images, paid APIs, and multi-tenant security.

---

## 2. Background and Theoretical Foundations

### 2.1 B-tree indexes

A B-tree is a balanced tree that keeps keys sorted and supports equality, range, and
ordered retrieval in `O(log n)` I/O for selective predicates. PostgreSQL’s default
index type is B-tree. It accelerates `=`, `<`, `<=`, `>`, `>=`, `BETWEEN`, and
`ORDER BY` on the indexed column, provided the predicate is sargable.

A B-tree does **not** accelerate `LIKE '%term%'` (a leading wildcard), because the
sorted order cannot prune the search space. This is central to the results in this
report.

### 2.2 Hash indexes

A hash index maps a key to a bucket and supports equality only. It cannot support
ranges or ordering. PostgreSQL hash indexes are compact and fast for exact matches,
but they are not a general-purpose replacement for B-trees.

### 2.3 Composite indexes and the leading-column rule

A multicolumn B-tree on `(a, b, c)` can be used when the query constrains a prefix of
the columns. A predicate on `a` alone, or `a` and `b`, can use the index; a predicate
on `b` alone generally cannot. Range predicates affect how later columns can be used:
after a range on `b`, column `c` is typically applied as a filter rather than a tight
index bound.

### 2.4 Vector embeddings and cosine distance

Sentence Transformers encode text into dense vectors. This project uses
`all-MiniLM-L6-v2`, which produces 384-dimensional vectors. After L2 normalisation,
cosine similarity is a dot product, and cosine distance is `1 − similarity`.

Semantic search finds products whose *meaning* is close to the query, even when the
exact words differ. For example, “wireless headphones” can match products tagged
“Bluetooth connectivity” because the embedding space places them near each other.

### 2.5 HNSW

Hierarchical Navigable Small World (HNSW) is a graph-based approximate
nearest-neighbour index. It builds a multi-layer proximity graph and searches from
the top layer downward, greedily moving toward the query vector. Parameters:

- `m` — number of bidirectional links per node (16 here);
- `ef_construction` — candidate list size during construction (64 here);
- `ef_search` — candidate list size at query time (100 here).

HNSW trades exactness for speed. Recall is not guaranteed; it depends on the
parameters and data.

### 2.6 Application caching

A cache stores the result of a previous computation keyed by the request. A TTL
limits staleness; an LRU policy bounds memory. A cache hit avoids both embedding and
database work, but a cache is stateful and is not a substitute for an index on
first-time queries.

---

## 3. Problem Statement and Requirements

### 3.1 Problem

Given a natural-language product query, return the top 5 or 10 products using a
user-selected retrieval method, and measure the method’s real database execution time
and access path on a 100,000-row dataset.

### 3.2 Functional requirements

| ID | Requirement |
|---|---|
| F1 | Exactly 100,000 products in PostgreSQL |
| F2 | Natural-language query input |
| F3 | Seven separately selectable methods |
| F4 | Top 5 / Top 10 result limits |
| F5 | Real execution timing |
| F6 | Repeated benchmark runs with statistics |
| F7 | Actual `EXPLAIN ANALYZE` output |
| F8 | Charts and comparison tables |
| F9 | CSV export |
| F10 | Dataset validation report |
| F11 | Automated tests |
| F12 | Local, free, open-source operation |

### 3.3 Non-functional requirements

- Parameterised SQL only; no SQL injection.
- No fabricated timings or mocked plans.
- Honest reporting when an index is not used.
- Reproducible setup and documented limitations.
- Responsive, usable interface.

---

## 4. System Architecture

The system is a Flask application with a PostgreSQL database. The browser sends JSON
to the API; the server parses the query, optionally embeds it, dispatches to exactly
one search module, executes parameterised SQL, captures a plan, and assembles a
response.

```text
Browser (HTML/CSS/JS + Chart.js)
        │
        ▼
Flask (routes → parser → embeddings → search dispatcher → benchmark)
        │
        ▼
PostgreSQL 19 + pgvector
  products (100,000 × 384-d embeddings)
  B-tree / hash / composite / HNSW indexes
```

Key modules:

- `app/query_parser.py` — rule-based natural-language parsing.
- `app/embeddings.py` — lazy Sentence Transformers model and vector conversion.
- `app/search/` — one module per method plus shared SQL helpers.
- `app/benchmark.py` — repetitions, statistics, CSV.
- `app/cache.py` — TTL/LRU cache.
- `app/plan.py` — EXPLAIN JSON normaliser.
- `app/routes.py` — HTTP API.

The full architecture is documented in `docs/architecture.md`.

### 4.1 Request flow

1. Validate the JSON body.
2. Parse the query into `ParsedQuery`.
3. Embed only for semantic methods.
4. Dispatch to the selected module.
5. Execute the result query and time it.
6. Execute `EXPLAIN ANALYZE` separately for the plan.
7. Return results, timing breakdown, SQL, parameters, plan, warnings, and
   comparability.

Timing is decomposed so that database work, embedding work, parsing, and plan
capture are not conflated.

---

## 5. Database Design

### 5.1 Schema

```sql
CREATE TABLE products (
    product_id       VARCHAR(10) PRIMARY KEY,
    name             TEXT NOT NULL,
    category         TEXT NOT NULL,
    brand            TEXT NOT NULL,
    price_inr        NUMERIC(12,2) NOT NULL CHECK (price_inr >= 0),
    color            TEXT,
    rating           NUMERIC(2,1) CHECK (rating >= 0 AND rating <= 5),
    stock_quantity   INTEGER NOT NULL CHECK (stock_quantity >= 0),
    use_case         TEXT,
    specifications   TEXT,
    description      TEXT,
    tags             TEXT,
    image_key        TEXT,
    image_prompt     TEXT,
    embedding        VECTOR(384)
);
```

### 5.2 Indexes

| Index | Type | Columns |
|---|---|---|
| `products_pkey` | B-tree | `product_id` |
| `idx_products_price_btree` | B-tree | `price_inr` |
| `idx_products_category_btree` | B-tree | `category` |
| `idx_products_rating_btree` | B-tree | `rating` |
| `idx_products_brand_hash` | Hash | `brand` |
| `idx_products_category_price_color_btree` | B-tree | `(category, price_inr, color)` |
| `idx_products_embedding_hnsw` | HNSW | `embedding` |

### 5.3 Storage

| Object | Size |
|---|---:|
| Table total | 465 MB |
| Heap | 86 MB |
| HNSW index | 191 MB |
| Composite B-tree | 10 MB |
| Brand hash | 6.4 MB |
| Primary key | 4.4 MB |
| Price B-tree | 4.1 MB |
| Rating B-tree | 3.1 MB |
| Category B-tree | 1.7 MB |

The HNSW index is the dominant storage cost, which is an important practical
trade-off: semantic search is fast at query time but expensive in space.

---

## 6. Dataset

### 6.1 Composition

- Exactly 100,000 rows.
- 10 categories × 10,000 products each: Camera, Gaming Accessories, Headphones,
  Keyboard, Laptop, Monitor, Smartphone, Smartwatch, Speaker, Tablet.
- 45 brands, 7 colours, 39 use-case labels.
- Prices: ₹501–₹279,993 (mean ₹60,490.48).
- Ratings: 2.8–5.0 (mean 3.898).
- Stock: 0–150.
- Product IDs: `P000001`–`P100000`.

### 6.2 Validation

The source CSV was validated read-only with UTF-8 BOM handling. All checks passed:

| Check | Result |
|---|---|
| Exact row count | PASS |
| Unique product IDs | PASS |
| Ten categories | PASS |
| 10,000 per category | PASS |
| No missing values | PASS |
| Prices numeric and non-negative | PASS |
| Ratings in range | PASS |
| Stock non-negative | PASS |
| No duplicate records | PASS |
| Product ID format | PASS |
| Complete ID range | PASS |

Full report: `docs/validation_report.md`.

### 6.3 Import and embeddings

The CSV was imported with `COPY FROM STDIN` in about 1.05 seconds. Embeddings were
generated for all 100,000 products using `all-MiniLM-L6-v2` on CPU at roughly 350
products/second, then normalised and stored as `VECTOR(384)`. The HNSW index was built
after the vectors were present.

---

## 7. Natural-Language Query Parsing

The parser is rule-based and deterministic. It extracts:

- **Category** — singular labels from the dataset (`Laptop`, `Headphones`, …),
  including plural forms.
- **Brand** — all 45 brands, including multi-word and hyphenated names.
- **Colour** — Black, Blue, Green, Grey, Red, Silver, White.
- **Price** — `under 80000`, `below 80k`, `above 20000`, `between 20000 and 30000`,
  `from 50000 to 90000`.
- **Use case** — recognised labels such as gaming, travel, photography,
  programming.
- **Keywords** — remaining meaningful terms, with practical synonyms
  (`wireless → bluetooth/wi-fi`, `lightweight → portable`, `noise → noise
  cancellation`).

### 7.1 Design decisions

- **No guessing.** An ambiguous phrase such as “around 50000” is not converted into a
  range; the parser leaves prices unset.
- **No false brand matches.** “noise cancelling headphones” does not treat “noise” as
  a brand.
- **Use case is soft.** A user may ask for “programming” even when no product in the
  category carries that exact label. Relational methods rank matching use cases first
  without excluding others; semantic methods keep the phrase in the embedded query.
- **Keyword fallback is explicit.** If exact keyword matching returns zero rows, the
  keyword predicate is relaxed while structured filters remain, and the fallback is
  reported in the response and UI. The reported time includes both attempts.

---

## 8. The Seven Methods

### 8.1 Full table scan

Same structured and keyword predicates, with index scans disabled:

```sql
SET LOCAL enable_indexscan = off;
SET LOCAL enable_indexonlyscan = off;
SET LOCAL enable_bitmapscan = off;
SET LOCAL enable_seqscan = on;
```

Observed plan: `Limit → Sort → Seq Scan`. This is a controlled baseline, not
PostgreSQL’s default plan.

### 8.2 B-tree

The same relational SQL with no planner settings. The planner chooses among the
category, price, rating, and composite B-trees.

### 8.3 Hash

The same SQL, with a brand equality predicate. When a brand is present, the hash
index can be used; when absent, the method reports that the hash index is not
applicable.

### 8.4 Composite B-tree

The same SQL, with `(category, price_inr, color)`. The index is applicable when the
leading column `category` is constrained. Colour after the price range is applied as
a filter.

### 8.5 HNSW

No structured filters:

```sql
SELECT ..., 1 - (embedding <=> %s::vector) AS similarity
FROM products
WHERE embedding IS NOT NULL
ORDER BY embedding <=> %s::vector
LIMIT %s;
```

`hnsw.ef_search = 100`.

### 8.6 Hybrid

Structured category/brand/colour/price predicates plus semantic ordering. The planner
may use a relational index, HNSW, or both.

### 8.7 Cached

A TTL/LRU cache around hybrid. A miss performs embedding and hybrid search; a hit
returns a deep copy with zero database and embedding time. Key = normalised query +
limit + method.

---

## 9. Benchmark Methodology

- Fixed suite of seven queries.
- Five measured repetitions per method (configurable 5–20).
- One unmeasured warm-up for non-cached methods.
- Application cache cleared before the cached method.
- Query parsed once; embedding computed once per semantic method to isolate database
  time.
- Statistics: median, mean, min, max, sample standard deviation, p95.
- One representative plan captured separately and excluded from statistics.
- Result overlap against the full scan reported.
- Comparability flags for relational, semantic, and cache groups.

Primary statistic: **median `db_execution_ms`**.

Full methodology: `docs/benchmark_methodology.md`.

---

## 10. Results

### 10.1 Fixed-suite medians

Five repetitions, limit 10, median database execution time in milliseconds:

| Query | Full scan | B-tree | Hash | Composite | HNSW | Hybrid | Cached |
|---|---:|---:|---:|---:|---:|---:|---:|
| Samsung smartphone | 10.378 | 0.886 | 0.763 | 0.747 | 0.558 | 3.453 | 0.000 |
| Laptops | 11.504 | 2.641 | 2.489 | 2.689 | 0.547 | 0.514 | 0.000 |
| Laptop under 80000 | 9.839 | 1.711 | 1.599 | 1.609 | 0.700 | 0.658 | 0.000 |
| Black laptop under 80000 | 9.333 | 0.728 | 0.608 | 0.576 | 1.088 | 1.644 | 0.000 |
| Lightweight laptop for programming | 23.813 | 17.054 | 16.706 | 19.946 | 0.593 | 0.606 | 0.000 |
| Wireless headphones for travel | 15.783 | 20.600 | 20.666 | 22.073 | 0.597 | 0.577 | 0.000 |
| Gaming monitor under 30000 | 10.129 | 1.670 | 1.501 | 1.490 | 0.863 | 0.937 | 0.000 |

### 10.2 Observed access paths

| Query | Relational plan | Vector plan |
|---|---|---|
| Samsung smartphone | category B-tree + brand hash | HNSW |
| Laptops | category B-tree | HNSW (hybrid) |
| Laptop under 80000 | category B-tree | HNSW (hybrid) |
| Black laptop under 80000 | composite B-tree | HNSW (pure), composite (hybrid) |
| Lightweight laptop for programming | category B-tree + `ILIKE` filters | HNSW |
| Wireless headphones for travel | category B-tree + `ILIKE` filters | HNSW |
| Gaming monitor under 30000 | category B-tree | HNSW |

The full scan always shows `Seq Scan` and zero indexes. The hash method shows the
brand hash index only when a brand is present.

### 10.3 Embedding cost

Semantic database times exclude embedding. In the fixed suite, query embedding took
approximately:

| Query | HNSW embedding (ms) | Hybrid embedding (ms) |
|---|---:|---:|
| Samsung smartphone | 15.484 | 3.339 |
| Laptops | 3.658 | 3.137 |
| Laptop under 80000 | 3.220 | 2.911 |
| Black laptop under 80000 | 3.689 | 4.099 |
| Lightweight laptop for programming | 3.932 | 3.310 |
| Wireless headphones for travel | 4.993 | 3.244 |
| Gaming monitor under 30000 | 4.045 | 3.092 |

The first value is higher because it was the first query after model load. The steady
state is roughly 3–5 ms per query on CPU. Adding embedding time to HNSW’s database
time gives an end-to-end semantic cost of roughly 4–6 ms, still competitive with the
relational methods for text-heavy queries.

### 10.4 Cache behaviour

The cached method starts with a real miss and then hits:

| Query | First run (miss) | Runs 2–5 |
|---|---:|---:|
| Samsung smartphone | 3.741 ms | 0 ms |
| Laptops | — | 0 ms |
| Laptop under 80000 | — | 0 ms |
| Black laptop under 80000 | 1.799 ms | 0 ms |
| Lightweight laptop for programming | — | 0 ms |
| Wireless headphones for travel | — | 0 ms |
| Gaming monitor under 30000 | — | 0 ms |

The median is 0 ms because four of five runs are hits. This is genuine cache
behaviour, not a fabricated zero.

### 10.5 Screenshots

- `docs/screenshots/01_landing.png` — landing page and dataset status.
- `docs/screenshots/02_search_results.png` — search results and metrics.
- `docs/screenshots/03_benchmark_dashboard.png` — Chart.js benchmark comparison.
- `docs/screenshots/04_technical_details.png` — SQL, plan, and buffers.

---

## 11. Analysis and Discussion

### 11.1 Indexes help selective structured predicates

For “Samsung smartphone”, the full scan took 10.378 ms, while the B-tree, hash, and
composite methods took 0.747–0.886 ms. The planner combined the category B-tree with
the brand hash index. This is the expected benefit of indexing: a highly selective
equality predicate reduces the number of rows examined by orders of magnitude.

For “Black laptop under 80000”, the composite index achieved 0.576 ms versus 9.333 ms
for the full scan. The leading category, price range, and colour filter align well
with the index.

### 11.2 Indexes do not help leading-wildcard text search

For “Lightweight laptop for programming”, the full scan took 23.813 ms and the
B-tree variants took 17.054–19.946 ms. The category index reduces the candidate set,
but every candidate must still be tested against several `ILIKE '%term%'` patterns.
The index does not reduce the dominant cost. In this case, the full scan is actually
faster than the B-tree variants, likely because the sequential scan has better
locality and avoids random heap access for a large fraction of the category.

This is an important negative result. Adding an index is not automatically an
optimisation; the index must match the predicate shape and selectivity.

For “Wireless headphones for travel”, the same effect appears more strongly: full scan
15.783 ms versus B-tree 20.600 ms, hash 20.666 ms, composite 22.073 ms. The keyword
synonym expansion increases the number of `ILIKE` patterns, which dominates the
runtime.

### 11.3 The planner is part of the experiment

The “B-tree” method sometimes used the composite index, and the “hash” method used
the composite index when no brand was present. This is not a bug: all indexes exist
in the same schema, and PostgreSQL chooses the cheapest plan. The application reports
the actual plan rather than pretending the method label restricts the planner.

This has a methodological implication: comparing “index types” by labelling queries
is weaker than comparing the plans PostgreSQL actually chooses. The technical panel
and the stored plan JSON make the real behaviour auditable.

### 11.4 Hash indexes are narrow but effective

The hash index was effective for exact brand equality (0.763 ms for “Samsung
smartphone”), but it cannot support ranges or ordering. When no brand was parsed, the
method explicitly reported non-applicability. A hash index is a specialised tool, not
a general replacement for a B-tree.

### 11.5 Composite index column order matters

The composite index `(category, price_inr, color)` was fastest when category, price,
and colour were all constrained. For “Laptop under 80000”, the planner preferred the
smaller single-column category index. Colour after the price range is applied as a
filter rather than a tight bound. A different order, such as
`(category, color, price_inr)`, would favour colour equality over price range. The
best order depends on the workload.

### 11.6 Semantic search is fast but different

HNSW produced the lowest database times in most queries (0.547–1.088 ms). It is
approximate and applies no structured filters, so its results can include products
from other categories and its ordering is semantic rather than by rating and price.
Adding the 3–5 ms embedding cost brings the end-to-end cost closer to the relational
methods.

Hybrid search combines the two: structured filters constrain the candidate set, and
semantic ranking orders it. Its database time ranged from 0.514 to 3.453 ms. For
“Samsung smartphone”, the planner used two relational indexes and still sorted by
vector distance, which is why hybrid was slower than pure HNSW there.

### 11.7 Caching changes the question

A cache hit is effectively free at the database level, but only for an identical
query and limit. The first query still pays the full cost. The benchmark reports the
miss and the hits separately, and the UI labels cache status. A cache is not a
substitute for an index; it is a complement for repeated workloads.

### 11.8 Summary of when each method helps

| Workload | Best fit |
|---|---|
| Exact brand/category lookup | Hash (brand) + B-tree (category) |
| Category + price range | B-tree or composite B-tree |
| Category + price + colour | Composite B-tree |
| Free-text keyword search | Full scan or semantic methods; B-tree does not help |
| Semantic similarity | HNSW |
| Structured + semantic | Hybrid |
| Repeated identical queries | Cache |

---

## 12. Testing and Validation

The project has **86 passing pytest tests** against the real database. Coverage
includes:

- dataset size, IDs, category balance, nulls, ranges, embeddings, indexes;
- 21 parser cases;
- all seven methods, result limits, filters, plans, applicability warnings;
- cache hit/miss/clear/TTL/LRU;
- benchmark statistics, repetition validation, CSV export;
- API errors, JSON 404/405, SQL injection safety;
- health endpoint and frontend serving.

The SQL injection test sends `laptop' OR 1=1; DROP TABLE products; --` and verifies
that the table still has 100,000 rows and that the payload appears only in bound
parameters, never in the SQL text.

Full test documentation: `docs/testing.md`.

---

## 13. Security and SQL Safety

- All user values are bound with psycopg `%s` placeholders.
- SQL text contains only fixed column names and fixed clauses.
- Planner settings are fixed strings defined in code, not user input.
- Request bodies are validated for type and range.
- Error responses do not expose stack traces; unexpected errors return a type and
  message only.
- The database uses trust authentication on localhost for local development only; this
  is not a production configuration.
- The app binds to `127.0.0.1` by default.

---

## 14. Performance and Resource Characteristics

- Table + indexes: 465 MB.
- HNSW index: 191 MB, built once after embedding.
- Embedding generation: several minutes on CPU for 100,000 products.
- Query embedding: roughly 3–5 ms steady state.
- Fixed-suite database times: 0.5–24 ms.
- Benchmark duration for seven methods × five repetitions: well under a second after
  warm-up, excluding model load.

The system is comfortable on a laptop with 4 GB+ RAM and about 1 GB of free disk.

---

## 15. Limitations

1. **Synthetic data.** The dataset is generated for demonstration, not real retail
   inventory. Distributions are balanced and may not reflect production skew.
2. **Single machine.** Results are specific to this hardware, PostgreSQL version, and
   cache state.
3. **Warm cache.** Cold-start behaviour is not measured by restarting PostgreSQL.
4. **Approximate vectors.** HNSW recall is not measured against exact nearest
   neighbours.
5. **CPU embeddings.** The model runs on CPU; GPU performance would differ.
6. **Keyword search.** Relational text matching uses `ILIKE` with synonym expansion,
   not full-text search or trigram indexes. This is deliberate, to show the limits of
   B-trees for leading-wildcard matching.
7. **In-process cache.** The cache is not shared across worker processes and is lost
   on restart.
8. **No images.** `image_key` and `image_prompt` are preserved, but images are
   intentionally postponed.
9. **Small sample size.** Five repetitions are enough for a clear signal but not for
   rigorous tail-latency analysis; p95 often equals the maximum.
10. **Planner variability.** Different PostgreSQL versions or statistics may choose
    different plans.

---

## 16. Conclusion

This project demonstrates a complete, honest pipeline for comparing database
retrieval techniques. It validates a 100,000-row dataset, builds relational and vector
indexes, implements seven separately selectable methods, measures real execution
times, captures real plans, and reports results with appropriate caveats.

The central finding is that indexing is workload-dependent. B-tree and hash indexes
dramatically improve selective structured predicates, but do not help leading-wildcard
text search. Composite indexes reward matching column order. HNSW provides fast
semantic retrieval at the cost of approximation, storage, and embedding time. Hybrid
search balances structure and semantics. Caching eliminates repeated work but changes
the meaning of a benchmark unless cache state is controlled.

The project also shows the importance of measurement discipline: separating database
time from embedding and plan-capture time, warming caches consistently, retaining raw
samples, and reporting when methods are not comparable. These practices matter as
much as the absolute numbers.

---

## 17. Future Work

1. Add trigram/GIN or PostgreSQL full-text search as an eighth method for fair
   text-search comparison.
2. Measure HNSW recall against exact nearest neighbours.
3. Add cold-start benchmarks with controlled PostgreSQL restarts.
4. Test with skewed, real-world-like data distributions.
5. Evaluate IVFFlat and other vector index types.
6. Add product images using the preserved `image_key` and `image_prompt`.
7. Support distributed caching (for example Redis) and multiple worker processes.
8. Add concurrency and load testing.
9. Tune HNSW `m`, `ef_construction`, and `ef_search` systematically.
10. Add query expansion and learning-to-rank for hybrid search.

---

## 18. References

1. PostgreSQL Global Development Group. *PostgreSQL 19 Documentation: Indexes*.
2. PostgreSQL Global Development Group. *PostgreSQL Documentation: EXPLAIN*.
3. pgvector. *Open-source vector similarity search for PostgreSQL*.
4. Malkov, Y. A., & Yashunin, D. A. (2020). Efficient and robust approximate nearest
   neighbor search using Hierarchical Navigable Small World graphs. *IEEE TPAMI*.
5. Reimers, N., & Gurevych, I. (2019). Sentence-BERT: Sentence embeddings using
   Siamese BERT-networks. *EMNLP*.
6. Hugging Face. *sentence-transformers/all-MiniLM-L6-v2* model card.
7. Flask. *Flask Documentation*.
8. Chart.js. *Chart.js Documentation*.

---

## 19. Appendix A — Reproduction Commands

```bash
# Database
bash scripts/start_postgres.sh

# Environment
source .venv/bin/activate

# Dataset and schema
python scripts/validate_dataset.py
python scripts/init_db.py
python scripts/import_data.py
python scripts/generate_embeddings.py

# Benchmarks
python scripts/run_benchmarks.py --repetitions 5 --limit 10

# Tests
pytest -q

# Application
python run.py
# http://127.0.0.1:5001
```

---

## 20. Appendix B — Project Artefacts

| Artefact | Path |
|---|---|
| Source dataset | `synthetic_products_100000.csv` |
| Validation report | `docs/validation_report.md` |
| Installation guide | `docs/installation.md` |
| Database setup | `docs/database_setup.md` |
| Architecture | `docs/architecture.md` |
| API reference | `docs/api.md` |
| Search methods | `docs/search_methods.md` |
| Benchmark methodology | `docs/benchmark_methodology.md` |
| Testing | `docs/testing.md` |
| Fixed-suite summary | `docs/benchmark_summary.md` |
| Raw benchmark CSV | `docs/benchmark_results.csv` |
| Full benchmark JSON | `data/benchmark_results.json` |
| Screenshots | `docs/screenshots/` |
| Tests | `tests/` |
| Source code | `app/`, `scripts/`, `templates/`, `static/` |

---

*All timings in this report were produced by executing the described system on the
development machine. They are not hardcoded and will vary on other hardware.*
