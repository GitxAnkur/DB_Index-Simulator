# The Seven Search Methods

Every method is a separate module in `app/search/`, separately selectable in the UI,
and separately benchmarked. The application never chooses a method automatically and
never substitutes a different method behind the user’s back.

Two rules apply to all methods:

1. **Actual plans only.** Index usage is read from `EXPLAIN (ANALYZE, BUFFERS,
   VERBOSE, FORMAT JSON)` when a plan is requested. The “expected index” is metadata,
   not a claim.
2. **Parameterised SQL only.** User values are bound as `%s` parameters. Method SQL
   differs only in fixed SQL text.

Interactive searches send `include_plan: false`, so no second `EXPLAIN` execution
runs and the reported database time reflects exactly one query. Plans remain available
through the API and test suite.

Before any method runs, the **scope gate** decides whether the query belongs to the
catalogue. A query is in scope when it names a category or brand, or when every
keyword has a word-boundary match in the product text (practical synonyms allowed).
Colour and price on their own are refinements, not scope. Out-of-scope queries return
zero products without touching the database.

Each search is also recorded against a **query ID** in the browser, so the Analysis
page can compare every method that was manually run for that exact query.

---

## 1. Full Table Scan (`full_scan`)

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

**Observed plan:** `Limit → Sort → Seq Scan on products`. No indexes.

**Interpretation:** the full scan is not always the slowest method. When the query
still has to evaluate expensive `ILIKE` predicates over a large category subset, an
index only helps if it reduces the work that dominates the query. This is an honest,
useful result.

**Limitation:** disabling index scans changes planner behaviour by design. This is a
controlled baseline, not a claim about PostgreSQL’s default plan for the same query.

---

## 2. B+ Tree (`btree`)

**Purpose:** demonstrate ordinary single-column B-tree indexes on equality and range
predicates. PostgreSQL implements B-tree indexes, which serve the B+ tree concept.

**Indexes available:**

- `idx_products_category_btree (category)`
- `idx_products_price_btree (price_inr)`
- `idx_products_rating_btree (rating)`

**Implementation:** identical relational SQL to `full_scan`, with no planner
settings. PostgreSQL chooses the access path, and the actual plan is reported.

**Observed plans:**

| Query | Observed access path |
|---|---|
| Samsung smartphone | category B-tree + brand hash |
| Laptops | `idx_products_category_btree` |
| Laptop under 80000 | `idx_products_category_btree` |
| Black laptop under 80000 | composite B-tree |
| Wireless headphones for travel | category B-tree + `ILIKE` filters |

**Key observation:** the planner is free to use the composite index even in the
“B+ Tree” method, because all indexes are present in the same schema. This is reported
as-is. The method label describes the *intended* index family, not a restriction on
the planner.

**Why some B-tree queries are slow:** `ILIKE '%keyword%'` cannot use a normal
B-tree. Once the category index produces ~10,000 candidate rows, every row must be
checked against several text patterns. That dominates the runtime.

**Limitation:** a B-tree does not accelerate leading-wildcard text search. A
trigram/GIN index would be the appropriate structure for that workload and is outside
this project’s seven methods.

---

## 3. Hash Index (`hash`)

**Purpose:** show the equality-only behaviour of PostgreSQL hash indexes.

**Index:** `idx_products_brand_hash ON products USING hash (brand)`.

**Implementation:** the same relational SQL. When a brand is parsed, the predicate
`brand = %s` can use the hash index. When no brand is parsed, the hash index is not
applicable.

**Observed plans:**

| Query | Brand parsed | Observed access path |
|---|---|---|
| Samsung smartphone | Samsung | `idx_products_brand_hash` + category B-tree |
| Black laptop under 80000 | none | composite index (hash not applicable) |
| Laptops | none | category B-tree |

When the hash index is not applicable, the API returns:

```json
{
  "hash_index_applicable": false,
  "note": "The query contains no brand, so the hash index is not applicable..."
}
```

and a UI warning.

**Interpretation:** the hash index is highly effective for exact brand equality, but
it cannot support ranges or ordering. For “Samsung smartphone”, the planner combines
it with the category B-tree because the query has both predicates.

**Limitation:** this project uses the hash index read-only for measurement, so
durability and replication behaviour are not being evaluated.

---

## 4. Composite Index (`composite_btree`)

**Purpose:** demonstrate a multicolumn index and the leading-column rule.

**Index:**

```sql
CREATE INDEX idx_products_category_price_color_btree
    ON products USING btree (category, price_inr, color);
```

**Implementation:** structured filters plus keyword predicates, ordered by
`price_inr, color, product_id` so the index can serve both the filter and the
ordering instead of falling back to a smaller single-column index.

**Observed plans:**

| Query | Observed access path |
|---|---|
| Black laptop under 80000 | `idx_products_category_price_color_btree` |
| Laptop under 80000 | `idx_products_category_price_color_btree` |
| Samsung smartphone | `idx_products_category_price_color_btree` |
| Laptops | `idx_products_category_price_color_btree` |
| Samsung under 50000 (no category) | `idx_products_price_btree` |

**Leading-column rule:** the composite index is usable when `category` is
constrained. Without a category predicate the index is reported as not applicable:

```json
{"leading_column_present": false}
```

**Column-order trade-off:** `color` comes after the range column `price_inr`, so a
colour equality cannot act as a tight index bound once a price range is present; it is
applied as a filter. A different column order would favour colour equality over price
range. This is a deliberate teaching example of column-order trade-offs.

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

**Observed plan:** `Limit → Index Scan using idx_products_embedding_hnsw`. The index
scan visits the HNSW graph and returns exactly `limit` rows. No structured filters are
applied, so the result set can include products from other categories.

**Similarity floor:** results below `HNSW_MIN_SIMILARITY` (default `0.30`) are
discarded. The scope gate already rejects unrelated prompts; the floor is a second
safety net for borderline queries.

**Measurement note:** HNSW and hybrid database times **exclude** query embedding
time. Embedding time is reported separately in the API and is not shown as part of
search performance in the UI.

**Approximation:** HNSW is approximate. Recall depends on `m`, `ef_construction`,
and `ef_search`; this project does not claim exact nearest neighbours.

**Result semantics:** cosine similarity is displayed as a percentage. HNSW results
are not directly comparable to relational results because there are no structured
filters and ordering is semantic, not by rating/price.

---

## 6. Hybrid (Filters + Vector) (`hybrid`)

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

**Iterative HNSW:** HNSW normally filters **after** the graph scan. With a selective
predicate the nearest `ef_search` candidates can all fail the filter, leaving an empty
or short result set. Hybrid therefore sets:

```sql
SET LOCAL hnsw.iterative_scan = relaxed_order;
```

so pgvector keeps traversing the graph until enough filtered rows are found.

**Observed plans:** the planner may use the HNSW index, one or more relational indexes,
or both. The actual plan is reported by the API; no index usage is claimed without
evidence.

**Use case as a soft hint:** `use_case` is not a hard `WHERE` clause. It remains in
the embedded query text, so “for programming” influences semantic ranking without
excluding products whose stored use-case label differs.

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

**Observed behaviour:** the first run is a miss (a real hybrid execution); repeated
identical queries are hits with 0 ms database time. This is a genuine measurement of
cache behaviour, not a fabricated zero: the miss sample is retained in the raw data
and CSV.

**Why this is not a database index:** the cache stores result sets in application
memory. It does not reduce database work for a first-time query and is not shared
across processes. It is included because caching is a standard retrieval optimisation
and its trade-off (state, staleness, memory) is worth measuring.

---

## Summary of observed access paths

Fixed suite, representative plans (5 repetitions, limit 10):

| Query | Full scan | B+ Tree | Hash | Composite | HNSW | Hybrid |
|---|---|---|---|---|---|---|
| Samsung smartphone | Seq Scan | category + brand hash | category + brand hash | composite | HNSW | category + brand hash |
| Laptops | Seq Scan | category | category | composite | HNSW | HNSW |
| Laptop under 80000 | Seq Scan | category | category | composite | HNSW | HNSW |
| Black laptop under 80000 | Seq Scan | composite | category | composite | HNSW | composite |
| Wireless headphones for travel | Seq Scan | category | category | composite | HNSW | HNSW |
| Gaming monitor under 30000 | Seq Scan | category | category | composite | HNSW | HNSW |

The single-column B-tree indexes remain part of the schema and are exercised by both
the B+ Tree method and the planner’s natural choices. The composite index is the
explicit multicolumn method.

This table is generated from `data/benchmark_results.json`; the actual plan JSON for
every method and query is stored there and can be requested through the API.
