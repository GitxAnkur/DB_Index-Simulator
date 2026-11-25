# Curated Demo Queries — One Query Per Index

This is the demo sheet for the 20-minute presentation. It lists the exact queries,
the methods to run, the real measured times, the actual PostgreSQL plan, and the
sentence to say for each one.

All numbers are **medians of 10 warm runs**, `limit = 5`, measured on this machine
on 25 November 2026. They are also stored in `docs/demo_query_results.json`.
Timings move by roughly ±0.1–1 ms between runs, so compare the medians and the order
of magnitude, not a single click.

> **Honesty rule:** never say “this index is fastest” without naming the query and
> the comparison. An index is fast only when its column and the query predicate
> match. Two cases are deliberately framed as baselines, not fake winners:
>
> - **Full table scan** is the no-index baseline. When no index applies, every
>   method becomes a scan and the times tie.
> - **Hybrid** is the best quality–speed trade-off for filtered semantic search.
>   On `Google pixel` it is also the fastest method overall; on other queries it
>   ties HNSW while enforcing filters.

---

## 1. Master table (what to run, what wins)

| # | Query | What it proves | Index actually used | Winner (median) | Runner-up |
|---:|---|---|---|---:|---|
| 1 | `wireless` | No index can serve a leading-wildcard keyword | **Seq Scan** (no index) | full / B+ Tree / Hash all ≈ 87–89 ms | tie |
| 2 | `laptop` | Single-column B-tree on category | `idx_products_category_btree` | **B+ Tree 2.84 ms** | Full scan 10.51 ms |
| 3 | `Motorola` | Hash index for brand equality | `idx_products_brand_hash` | **Hash 0.54 ms** | Hybrid 0.79 ms |
| 4 | `black laptop under 80000` | Composite index covers filter + order | `idx_products_category_price_color_btree` | **Composite 0.118 ms** | Hash 0.60 ms |
| 5 | `lightweight laptop for travel` | Semantic search when words do not match | `idx_products_embedding_hnsw` | **HNSW 0.91 ms** | Hybrid 0.92 ms |
| 6 | `Google pixel` | Filters + semantic ranking in one query | `idx_products_embedding_hnsw` + brand filter | **Hybrid 0.71 ms** | HNSW 0.82 ms |
| 7 | repeat query 4 with `cached` | Application cache, not a database index | none on a hit | **Cached 0.00 ms** | Composite 0.118 ms |
| 8 | `flying car` | Scope gate rejects nonsense before SQL | none — no SQL | **0.00 ms, 0 rows** | — |

The fastest **raw** method for each query is in bold. For queries 1 and 5–6 the
difference between the top two is tiny; explain the tie honestly.

---

## 2. Query 1 — `wireless` (no index applies)

**Run:** `full_scan`, `btree`, `hash`
**Limit:** 5
**Parsed:** keyword `wireless`; no category, brand, colour, or price

**Actual plan (all three methods):**

```text
Limit
  Gather Merge
    Sort
      Parallel Seq Scan on products
        Filter: name/description/tags/specifications/use_case ILIKE '%wireless%'
```

**Measured:**

| Method | Median | Plan |
|---|---:|---|
| Full Table Scan | 88.91 ms | Seq Scan |
| B+ Tree | 88.36 ms | Seq Scan (planner rejects indexes) |
| Hash | 86.76 ms | Seq Scan (planner rejects indexes) |

**Verdict:** statistical tie. No index can answer `ILIKE '%wireless%'`, because a
leading wildcard destroys the sorted order a B-tree depends on and hash indexes only
support equality. The database must read the table and test the text. About 10,088
rows match, so the work is real.

**Say this:**

> This is our control query. There is no category, brand, colour, or price — only a
> word that can appear anywhere in the text. A B-tree cannot help with a leading
> `%`, and a hash index cannot help at all. PostgreSQL correctly falls back to a
> sequential scan. The three methods are within noise of each other, and that is the
> lesson: an index only helps when the predicate matches the index.

**If sir asks “why is full scan not slowest?”**
It is not “fast” — it is the only option. The indexed methods also become scans, so
they cannot beat it. The ~88 ms is the cost of reading 100,000 rows and running five
`ILIKE` checks.

---

## 3. Query 2 — `laptop` (single-column B+ Tree)

**Run:** `full_scan`, `btree`
**Limit:** 5
**Parsed:** category `Laptop`

**Actual plan:**

```text
Limit
  Sort  (rating DESC, price ASC, product_id)
    Bitmap Heap Scan on products
      Recheck Cond: category = 'Laptop'
      Bitmap Index Scan on idx_products_category_btree
```

**Measured:**

| Method | Median | Rows matched by filter |
|---|---:|---:|
| Full Table Scan | 10.51 ms | 10,000 |
| **B+ Tree** | **2.84 ms** | 10,000 |

**Verdict:** the category B-tree cuts the work by about **3.7×**. It finds the 10,000
Laptop rows, then PostgreSQL sorts them by rating and returns 5. The planner uses a
**Bitmap Index Scan**, not a plain Index Scan, because 10% of the table matches: it
collects row locations first and reads the heap in physical order, which is cheaper
for this selectivity.

**Say this:**

> The query names one category. The B-tree on `category` jumps straight to the
> 10,000 Laptop rows instead of reading all 100,000. PostgreSQL chooses a bitmap
> scan because one category is 10% of the table. The remaining cost is the sort by
> rating. This is the single-column B+ Tree doing exactly its job.
>
> Note: a composite index on category + price would be even faster for this query.
> We show that in query 4. The B+ Tree is the best *single-column* path, not the
> best possible index for every category query.

**Why not hash?** Hash is on `brand`; this query has no brand. Hash cannot help a
category equality.

---

## 4. Query 3 — `Motorola` (hash index on brand)

**Run:** `full_scan`, `hash`, `composite_btree`, `hnsw`, `hybrid`
**Limit:** 5
**Parsed:** brand `Motorola`

**Actual plan (hash):**

```text
Limit
  Sort
    Bitmap Heap Scan on products
      Bitmap Index Scan on idx_products_brand_hash
        Index Cond: brand = 'Motorola'
```

**Measured:**

| Method | Median | Actual index | Rows |
|---|---:|---|---:|
| Full Table Scan | 9.14 ms | none (Seq Scan) | 5 |
| **Hash** | **0.54 ms** | `idx_products_brand_hash` | 5 |
| Hybrid | 0.79 ms | HNSW | 5 |
| HNSW | 0.97 ms | HNSW | 5 |
| Composite method | 1.09 ms | `idx_products_price_btree` + brand filter | 5 |

**Verdict:** hash is the clear winner. `Motorola` is an equality predicate and the
brand column has 1,272 matching rows. The hash index goes directly to that bucket —
no range, no ordering requirement. The plan still sorts the 1,272 rows by rating, but
that is cheap.

**Why the composite method is slower here:** the composite index is
`(category, price_inr, color)`. This query has **no category**, so the leading column
is missing and the composite index cannot be used. The planner falls back to the
price B-tree, scans prices in order, and filters `brand = 'Motorola'` until it finds
5 rows. That is more work than jumping straight to the brand bucket.

**Say this:**

> A brand is an exact equality. The hash index computes the hash of `Motorola` and
> goes straight to its bucket. It does not support ranges or sorting, but we do not
> need those here. This is why the hash index is the right tool for brand equality
> and the wrong tool for “under 80000”.
>
> The composite index cannot help because category is missing — that is the
> leading-column rule.

**If sir asks “why not use hash for everything?”**
Hash supports equality only. It cannot answer `price <= 80000`, cannot return rows in
price order, and cannot help a category range. It is a specialist, not a general index.

---

## 5. Query 4 — `black laptop under 80000` (composite index)

**Run:** `full_scan`, `btree`, `hash`, `composite_btree`, `hnsw`, `hybrid`
**Limit:** 5
**Parsed:** category `Laptop`, colour `Black`, max price `80000`

**Rows that satisfy the filters:** 373 (0.37% of the table)

**Actual plan (composite method):**

```text
Limit
  Incremental Sort
    Index Scan on idx_products_category_price_color_btree
      Index Cond: category = 'Laptop' AND color = 'Black'
      Filter: price_inr <= 80000
```

**Measured:**

| Method | Median | Actual plan |
|---|---:|---|
| Full Table Scan | 9.83 ms | Seq Scan + filter + sort |
| B+ Tree | 0.63 ms | Bitmap Index Scan on composite + sort |
| Hash | 0.60 ms | Bitmap Index Scan on composite + sort |
| **Composite** | **0.118 ms** | Index Scan on composite + incremental sort |
| HNSW | 1.60 ms | HNSW graph, no filters |
| Hybrid | 1.70 ms | HNSW + filters |

**Verdict:** the composite index wins by ~5× over the other relational methods and
~80× over the full scan. All three relational methods use the **same** composite
index, but differently:

- B+ Tree and Hash use it as a **bitmap** to find the 373 matching rows, then sort
  those rows by rating.
- Composite orders by `price_inr, color, product_id`, which matches the index order,
  so PostgreSQL can walk the index and stop after 5 rows. No full sort.

**Why colour is in the index condition but price is a filter:** the index order is
`(category, price_inr, color)`. A range on `price_inr` would prevent using `color` as
a tight boundary after it, so PostgreSQL uses `category + color` as the index
condition and checks `price_inr <= 80000` as a filter. The index still narrows
100,000 rows to 373.

**Say this:**

> This is the query the composite index was built for: category, price, and colour.
> All relational methods find the same index, but only the composite method orders
> results the way the index is stored — price and colour. It walks the index and
> stops after five rows. The others fetch the 373 matches and sort by rating, so
> they pay a sort cost. Same index, different ordering, different time.
>
> This is also why column order matters. Category is first because every query must
> constrain it. Price is before colour, so a price range is a filter rather than a
> second boundary.

**If sir asks “why not put colour first?”**
Then category+price queries would lose the leading column. We chose the order that
matches the most common workload: category first, then price, then colour.

---

## 6. Query 5 — `lightweight laptop for travel` (HNSW semantic search)

**Run:** `btree`, `composite_btree`, `hnsw`, `hybrid`
**Limit:** 5
**Parsed:** category `Laptop`, use case `travel`, keyword `lightweight`

**Important dataset fact:** the word `lightweight` appears **0 times** in the
product text. Relational methods therefore return **0 rows**, even after scanning
10,000 laptops. HNSW returns 5 laptops based on meaning.

**Measured:**

| Method | Median | Rows | Plan |
|---|---:|---:|---|
| B+ Tree | 14.25 ms | **0** | Bitmap category B-tree + ILIKE filter |
| Composite | 15.02 ms | **0** | Composite index + ILIKE filter |
| **HNSW** | **0.91 ms** | **5** | HNSW index scan |
| Hybrid | 0.92 ms | 5 | HNSW + category filter |

**Verdict:** HNSW is the fastest useful method and the only exact index scan. It is
not “faster at the same job”; it is doing a different job. It converts the query to a
384-dimensional vector and walks the HNSW graph for the nearest meanings. It is
approximate, and it does not enforce structured filters.

**Say this:**

> The customer said “lightweight”, but our catalogue never uses that word. The
> B-tree and composite index scan 10,000 laptops, find zero matches, and waste
> 14–15 ms. HNSW does not look for the word; it compares the meaning of the query
> with the meaning of each product and returns five sensible laptops in under a
> millisecond.
>
> This is the trade-off: relational indexes are exact but literal; vector indexes
> are semantic but approximate. HNSW cannot guarantee “only Laptop” or “under
> 80000” — that is why we also built hybrid.

**If sir asks “is HNSW always right?”**
No. It is approximate, it ignores hard filters, and its recall depends on `m`,
`ef_construction`, and `ef_search`. For exact category/price queries, a relational
index is better.

---

## 7. Query 6 — `Google pixel` (hybrid: filter + vector)

**Run:** `hash`, `composite_btree`, `hnsw`, `hybrid`
**Limit:** 5
**Parsed:** brand `Google`, keyword `pixel`

**Measured:**

| Method | Median | Rows | Plan |
|---|---:|---:|---|
| Hash | 1.14 ms | 5 | Brand hash + ILIKE `pixel` + sort |
| Composite | 1.13 ms | 5 | Brand hash + ILIKE `pixel` + sort |
| HNSW | 0.82 ms | 5 | HNSW graph, no brand filter |
| **Hybrid** | **0.71 ms** | **5** | HNSW graph + `brand = 'Google'` filter |

**Verdict:** hybrid is the fastest method for this query while also **guaranteeing**
that every row is a Google product. HNSW is close, but it does not enforce the brand
filter; it simply happens to return Google Pixel phones because the query text says
“Google”. Hybrid makes the filter a hard condition.

**Say this:**

> Here we combine a hard filter with semantic ranking. Hybrid walks the HNSW graph
> and keeps only rows where `brand = 'Google'`. It is slightly faster than plain
> HNSW and about 35% faster than the hash path, because the graph narrows the
> candidates before the brand check. More importantly, it guarantees the filter.
>
> This is the best of both worlds when the user says “Google Pixel” rather than just
> “a phone”.

**If sir asks “why did the hash path not win?”**
Hash finds all 1,242 Google rows, then filters `pixel` with `ILIKE`, then sorts. That
is more work than walking the vector graph and checking the brand on the candidates.

---

## 8. Query 7 — cached repeat (application cache, not an index)

**Run:** after query 4, run `cached` twice on `black laptop under 80000`.
**Limit:** 5

**Measured:**

| Run | Cache status | DB time | Embedding time |
|---|---|---:|---:|
| First | miss | 1.64 ms | 2.77 ms |
| Second | hit | **0.00 ms** | 0.00 ms |
| Third | hit | **0.00 ms** | 0.00 ms |

**Verdict:** the second and third runs are faster because the result set is already
in memory. This is **not** a database index. The cache key is
`method | normalised query | limit`; a hit returns a deep copy and never touches
PostgreSQL. It is per-process, has a 300-second TTL, and holds up to 512 entries with
LRU eviction.

**Say this:**

> The cache is a different optimisation. On the first run it misses and executes the
> hybrid search. On the next identical run it returns the saved result set with zero
> database time. It is not an index, it is not shared between servers, and it can go
> stale — but for repeated queries it is the fastest possible answer.

**If sir asks “why is the first run slower?”**
That is the real query. The cache cannot help until it has seen the query. We keep
the miss in the data instead of hiding it.

---

## 9. Query 8 — `flying car` (scope gate, no SQL)

**Run:** any method (use `full_scan`)
**Result:** `out_of_scope = true`, `result_count = 0`, `db_execution_ms = 0.0`,
`technical.sql = null`

**Say this:**

> A vector index always returns some nearest neighbours, even for nonsense. Before
> any method runs, our scope gate checks whether the query belongs to the catalogue:
> it needs a category, a brand, or keywords that actually appear in the product text.
> “Flying car” has none, so we return zero results in zero milliseconds and execute
> no SQL. The user gets an honest answer instead of five random products.

---

## 10. Backup queries (if sir asks for more)

| Query | Why use it | Expected result |
|---|---|---|
| `Samsung smartphone` | Brand + category: hash + category B-tree | ~0.7 ms hash; composite ~0.14 ms |
| `Sony headphones` | Brand + category: hash + category B-tree | ~0.7 ms hash |
| `wireless headphones` | Category + keyword: category B-tree, composite | Composite ~0.5 ms; B+ Tree ~20 ms |
| `noise cancelling` | Open-ended semantic, no filter | HNSW ~0.75 ms; hybrid ~0.80 ms |
| `Logitech wireless mouse` | Brand + keyword: hybrid enforces brand | HNSW ~0.74 ms; hybrid ~0.76 ms; B+ Tree ~3.9 ms |
| `black laptop for programming under 80000` | Hybrid enforces black + price + semantic | Hybrid ~1.3 ms; HNSW ~1.2 ms; composite ~0.12 ms |

---

## 11. Why the other indexes take more time — one-page answer

| Reason | What it means in this demo |
|---|---|
| **Full scan reads everything** | 100,000 rows; five `ILIKE` checks per row; ~88 ms for `wireless`. |
| **Wrong index, or no usable column** | Hash on `brand` cannot help a category query. Composite needs `category` first. HNSW cannot enforce `price <= 80000`. |
| **Index scan + sort** | B+ Tree and Hash can find rows, but their `ORDER BY rating` differs from the index order, so they sort the matches. Composite orders by price/colour, matching the index, so it stops after 5. |
| **Bitmap vs plain index scan** | At 10% selectivity (Laptop, 10,000 rows), PostgreSQL prefers a bitmap scan. At 0.37% selectivity (black laptops under 80k, 373 rows), a plain index scan is cheap. |
| **Semantic mismatch** | Relational methods need the literal word; `lightweight` is absent, so they return 0 after a 14 ms scan. HNSW works on meaning. |
| **Graph approximation** | HNSW walks a multi-layer graph and stops at `ef_search` candidates; it is fast but approximate and ignores filters. |
| **Cache state** | A hit avoids the database completely; a miss is a normal query. |

---

## 12. Demo order and click path (6–7 minutes)

1. Clear the analysis history in the browser (Analysis → “Clear all analyses”).
2. `wireless` → Full Table Scan → B+ Tree → Hash. Leave the query unchanged.
3. `laptop` → Full Table Scan → B+ Tree.
4. `Motorola` → Full Table Scan → Hash → Composite → HNSW → Hybrid.
5. `black laptop under 80000` → Full Table Scan → B+ Tree → Hash → Composite →
   HNSW → Hybrid → Cached (run twice).
6. `lightweight laptop for travel` → B+ Tree → Composite → HNSW → Hybrid.
7. `Google pixel` → Hash → Composite → HNSW → Hybrid.
8. `flying car` → Full Table Scan (show the notice and 0 ms).
9. Open Analysis. Point at the query IDs and click between them.

**Tip:** after each search, the query ID appears on the result card. The same query
with a new method updates the same graph; a new query creates a new ID and a new
graph.
