# The Seven Search Methods

Every method is a separate module in `app/search/`, separately selectable in the UI,
and separately benchmarked. The application never chooses a method automatically and
never substitutes a different method behind the user’s back.

Two rules apply to all methods:

1. **Actual plans only.** Index usage is read from `EXPLAIN (ANALYZE, BUFFERS,
   VERBOSE, FORMAT JSON)` and displayed. The “expected index” is metadata, not a
   claim.
2. **Parameterised SQL only.** User values are bound as `%s` parameters. Method SQL
   differs only in fixed SQL text.

---

## 1. Normal Search / Full Table Scan (`full_scan`)

**Purpose:** a baseline that shows the cost of examining the table without index
access paths.

**Implementation:** the same structured filters and keyword predicate as the other
relational methods, executed inside a transaction with:

```sql
SET LOCAL enable_indexscan = off;
SET LOCAL enable_indexonlyscan = off;
SET LOCAL enable_bitmapscan = off;
SET LOCAL enable_seqscan = on;
```

**SQL shape:**

```sql
SELECT product_id, name, category, brand, price_inr, color, rating,
       stock_quantity, use_case, specifications, description, tags,
       image_key, image_prompt
FROM products
WHERE category = %s AND color = %s AND price_inr <= %s
ORDER BY rating DESC NULLS LAST, price_inr ASC, product_id ASC
LIMIT %s;
```

**Observed plan:** `Limit → Sort → Seq Scan on products`. No indexes. For
“Black laptop under 80000” the scan reads the heap and returns 10 rows after
filtering 373 matching rows.

**Interpretation:** the full scan is not always the slowest method. For
“Lightweight laptop for programming” it is 23.8 ms, while the B-tree variants are
17–20 ms, because those variants must still evaluate expensive `ILIKE` predicates on
a large category subset. This is an honest, useful result: an index only helps when
it reduces the work that dominates the query.

**Limitation:** disabling index scans changes planner behaviour by design. This is a
controlled baseline, not a claim about PostgreSQL’s default plan for the same query.

---

## 2. B+ Tree Search (`btree`)

**Purpose:** demonstrate ordinary single-column B-tree indexes on equality and range
predicates.

**Indexes available:**

- `idx_products_category_btree (category)`
- `idx_products_price_btree (price_inr)`
- `idx_products_rating_btree (rating)`

**Implementation:** identical relational SQL to `full_scan`, with no planner
settings. PostgreSQL chooses the access path.

**Observed plans:**

| Query | Observed access path |
|---|---|
| Samsung smartphone | `idx_products_category_btree` + `idx_products_brand_hash` (BitmapAnd/Index Scan) |
| Laptops | `idx_products_category_btree` |
| Laptop under 80000 | `idx_products_category_btree` |
| Black laptop under 80000 | `idx_products_category_price_color_btree` |
| Lightweight laptop for programming | `idx_products_category_btree` + `ILIKE` filters |
| Wireless headphones for travel | `idx_products_category_btree` + `ILIKE` filters |

**Key observation:** the planner is free to use the composite index even in the
“B-tree” method, because all indexes are present in the same schema. This is reported
as-is. The method labels describe the *intended* index family, not a restriction on
the planner.

**Why some B-tree queries are slow:** `ILIKE '%keyword%'` cannot use a normal
B-tree. Once the category index produces ~10,000 candidate rows, every row must be
checked against several text patterns. That dominates the runtime.

**Limitation:** a B-tree does not accelerate leading-wildcard text search. A
trigram/GIN index would be the appropriate structure for that workload and is outside
this project’s seven methods.

---

## 3. Hash Index Search (`hash`)

**Purpose:** show the equality-only behaviour of PostgreSQL hash indexes.

**Index:** `idx_products_brand_hash ON products USING hash (brand)`.

**Implementation:** the same relational SQL. When a brand is parsed, the predicate
`brand = %s` can use the hash index. When no brand is parsed, the hash index is not
applicable.

**Observed plans:**

| Query | Brand parsed | Observed access path |
|---|---|---|
| Samsung smartphone | Samsung | `idx_products_brand_hash` + `idx_products_category_btree` |
| Black laptop under 80000 | none | composite B-tree (hash not applicable) |
| Laptops | none | category B-tree |

When the hash index is not applicable, the API returns:

```json
{
  "hash_index_applicable": false,
  "note": "The query contains no brand, so the hash index is not applicable..."
}
```

and a UI warning.

**Interpretation:** the hash index is highly effective for exact brand equality
(0.76 ms for “Samsung smartphone” versus 10.4 ms full scan), but it cannot support
ranges or ordering. For “Samsung smartphone”, the planner combines it with the
category B-tree because the query has both predicates.

**Limitation:** PostgreSQL hash indexes are not WAL-logged in the same way as
B-trees in older versions; this project uses them read-only for benchmarking, so
durability is not being evaluated.

---

## 4. Composite B+ Tree Search (`composite_btree`)

**Purpose:** demonstrate a multicolumn index and the leading-column rule.

**Index:**

```sql
CREATE INDEX idx_products_category_price_color_btree
    ON products USING btree (category, price_inr, color);
```

**Implementation:** the same relational SQL.

**Observed plans:**

| Query | Observed access path |
|---|---|
| Black laptop under 80000 | `idx_products_category_price_color_btree` (0.576 ms) |
| Laptop under 80000 | `idx_products_category_btree` |
| Samsung smartphone | category B-tree + brand hash |
| Laptops | category B-tree |

**Leading-column rule:** the composite index is usable when `category` is
constrained. Without a category predicate the index is reported as not applicable:

```json
{"leading_column_present": false}
```

**Why “Laptop under 80000” does not use the composite index:** the single-column
category index is smaller and sufficient for the leading equality; the planner
chooses it. The composite index shows its advantage when category, price, and colour
are all constrained (“Black laptop under 80000”: 0.576 ms).

**Limitation:** `color` comes after the range column `price_inr`, so it cannot be
used as a tight index bound after a price range; it is applied as a filter. A
different column order would favour colour equality over price range. This is a
deliberate teaching example of column-order trade-offs.

---

## 5. HNSW Vector Search (`hnsw`)

**Purpose:** approximate nearest-neighbour semantic retrieval over real embeddings.

**Model:** `sentence-transformers/all-MiniLM-L6-v2`, 384 dimensions, CPU, normalised
vectors.

**Index:**

```sql
CREATE INDEX idx_products_embedding_hnsw
    ON products USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);
```

**SQL shape:**

```sql
SELECT product_id, ..., 1 - (embedding <=> %s::vector) AS similarity
FROM products
WHERE embedding IS NOT NULL
ORDER BY embedding <=> %s::vector
LIMIT %s;
```

`SET LOCAL hnsw.ef_search = 100` is applied per transaction.

**Observed plan:** `Limit → Index Scan using idx_products_embedding_hnsw`. The
index scan visits the HNSW graph and returns exactly `limit` rows. No structured
filters are applied, so the result set can include products from other categories.

**Observed medians:** 0.547–1.088 ms database time for the fixed suite.

**Important measurement note:** HNSW and hybrid database times **exclude** query
embedding time. Embedding took roughly 2.9–15.5 ms per query in the fixed suite
(the first call in a fresh process can be much slower while the model loads). The
UI shows embedding time separately; adding it gives the end-to-end semantic cost.

**Approximation:** HNSW is approximate. Recall depends on `m`, `ef_construction`,
and `ef_search`; this project does not claim exact nearest neighbours. With 100,000
vectors and `ef_search = 100`, results are stable across repetitions in practice.

**Result semantics:** cosine similarity is displayed as a percentage. HNSW results
are not directly comparable to relational results because there are no structured
filters and ordering is semantic, not by rating/price.

---

## 6. B+ Tree + HNSW Hybrid Search (`hybrid`)

**Purpose:** combine hard structured filters with semantic ranking.

**Implementation:**

1. Apply parsed category, brand, colour, min price, and max price as SQL predicates.
2. Order the filtered rows by cosine distance to the query embedding.
3. Return `limit` rows with similarity.

```sql
SELECT product_id, ..., 1 - (embedding <=> %s::vector) AS similarity
FROM products
WHERE embedding IS NOT NULL
  AND category = %s
  AND color = %s
  AND price_inr <= %s
ORDER BY embedding <=> %s::vector
LIMIT %s;
```

**Observed plans:**

| Query | Observed access path |
|---|---|
| Samsung smartphone | category B-tree + brand hash |
| Laptops | HNSW index |
| Black laptop under 80000 | composite B-tree |
| Wireless headphones for travel | HNSW index |

The plan depends on selectivity: a highly selective structured filter is cheaper to
apply first, while a broad category may be cheaper to traverse with HNSW.

**Use case as a soft hint:** `use_case` is not a hard `WHERE` clause. It remains in
the embedded query text, so “for programming” influences semantic ranking without
excluding products whose stored use-case label differs.

**Observed medians:** 0.514–3.453 ms database time. The “Samsung smartphone” hybrid
is slower (3.45 ms) because the planner combines two relational indexes and still
sorts by vector distance.

**Comparability:** not comparable to relational methods. Hybrid returns a different
ordering and applies semantic ranking; it also incurs embedding time.

---

## 7. Cached Search (`cached`)

**Purpose:** demonstrate application-level caching and cache-hit behaviour.

**Implementation:** an in-process TTL + LRU cache wraps **hybrid** search.

- Key: hash of normalised query + limit + method.
- Miss: embed, run hybrid, store a deep copy, return `cache.status = "miss"`.
- Hit: return a deep copy, `db_execution_ms = 0`, `embedding_ms = 0`,
  `cache.status = "hit"`.
- TTL: 300 seconds by default (`CACHE_TTL_SECONDS`).
- Capacity: 512 entries (`CACHE_MAX_ENTRIES`), LRU eviction.
- Statistics: hits, misses, evictions, expirations, hit rate.
- Clearing: `POST /api/cache/clear` or `DELETE /api/cache/clear`.

**Observed benchmark behaviour:** the benchmark clears the cache before the cached
method. Run 1 is a miss (a real hybrid execution, e.g. 1.8–3.7 ms); runs 2–5 are
hits (0 ms database time). The median is therefore 0.0 ms. This is a genuine
measurement of cache behaviour, not a fabricated zero: the miss sample is retained
in the raw data and CSV.

**Why this is not a database index:** the cache stores result sets in application
memory. It does not reduce database work for a first-time query and is not shared
across processes. It is included because caching is a standard retrieval optimisation
and its trade-off (state, staleness, memory) is worth measuring.

---

## Summary of observed access paths

Fixed suite, representative plans (5 repetitions, limit 10):

| Query | Full scan | B-tree | Hash | Composite | HNSW | Hybrid |
|---|---|---|---|---|---|---|
| Samsung smartphone | Seq Scan | category + brand hash | category + brand hash | category + brand hash | HNSW | category + brand hash |
| Laptops | Seq Scan | category | category | category | HNSW | HNSW |
| Laptop under 80000 | Seq Scan | category | category | category | HNSW | HNSW |
| Black laptop under 80000 | Seq Scan | composite | composite | composite | HNSW | composite |
| Lightweight laptop for programming | Seq Scan | category | category | category | HNSW | HNSW |
| Wireless headphones for travel | Seq Scan | category | category | category | HNSW | HNSW |
| Gaming monitor under 30000 | Seq Scan | category | category | category | HNSW | HNSW |

This table is generated from `data/benchmark_results.json`; the actual plan JSON for
every method and query is stored there and shown in the UI.
