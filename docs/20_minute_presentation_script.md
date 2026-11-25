# 20-Minute Presentation Script

**Project:** Indexed Product Search — A Comparative Study of Database Indexing  
**Team:** three members (replace `MEMBER 1`, `MEMBER 2`, `MEMBER 3` with real names)  
**Total time:** 20:00  
**Slides:** `docs/DBMS_Index_Project_Presentation.pptx`  
**Demo sheet:** `docs/curated_demo_queries.md`  
**Evidence:** `docs/demo_query_results.json`

This script is written to be spoken, not read. Short sentences. One idea per slide.
The demo is the centre of the presentation; the slides only support it.

---

## Before you start (10 minutes before)

1. Start PostgreSQL:

   ```bash
   cd /Users/ankurdhanraj/Desktop/dbms_2
   bash scripts/start_postgres.sh
   ```

2. Start Flask:

   ```bash
   source .venv/bin/activate
   python run.py
   ```

3. Open **http://127.0.0.1:5001** in the demo browser.

4. Open **http://127.0.0.1:5001/api/health** once and confirm:
   - 100,000 products
   - 100,000 embeddings
   - pgvector 0.8.7
   - seven valid indexes

5. In **Analysis**, click **Clear all analyses**. Start with a clean graph list.

6. Keep `docs/curated_demo_queries.md` open on a second screen or phone.

7. Do **not** run the full test suite during the demo. It is already verified:
   `101 passed`.

---

## Who does what

| Member | Role | DBMS work they own | Demo segment |
|---|---|---|---|
| **MEMBER 1** | Data & Database Engineer | Dataset design and validation; schema; all seven indexes and their column order; import pipeline; 384-d embeddings; index size and validity checks | Opening, dataset, schema, index inventory |
| **MEMBER 2** | Backend & Search Engineer | Natural-language parser; scope gate; SQL builder; all seven method modules; connection pool; timing methodology; `EXPLAIN` capture; cache; benchmark API | Architecture, request journey, parser, timing |
| **MEMBER 3** | Analysis, Testing & Demo Engineer | Query-specific analysis dashboard; query IDs; chart and query list; 101-test suite; curated demo queries; verification of every claim against the real DB | Live demo, analysis page, testing, limitations |

Every member can run the app and answer basic questions. The division above is the
detailed ownership, not a wall between people.

---

## Timeline

| Time | Speaker | Slides | Content |
|---|---|---|---|
| 0:00–0:40 | Member 1 | 1 | Title and team |
| 0:40–2:00 | Member 1 | 2–3 | Problem, goal, what we built |
| 2:00–3:15 | Member 1 | 4 | Tech stack and how the database connects |
| 3:15–5:30 | Member 1 | 5–6 | Dataset, schema, seven indexes |
| 5:30–7:30 | Member 2 | 7–8 | Architecture, end-to-end journey |
| 7:30–9:15 | Member 2 | 9–10 | Parser, scope gate, seven methods |
| 9:15–10:30 | Member 2 | 11 | Fair timing, plans, evidence |
| 10:30–16:30 | Member 3 | 12–13 | Live demo: six queries + cache + out-of-scope |
| 16:30–17:30 | Member 3 | 14 | Query-specific analysis dashboard |
| 17:30–18:30 | All | 15 | Work division (20 seconds each) |
| 18:30–19:20 | Member 3 | 16–17 | Testing, limitations, what we learned |
| 19:20–20:00 | All | 18 | Conclusion and Q&A |

If you are running late, cut the `wireless` demo to one method and skip the
`Google pixel` query. Never cut the work division or the conclusion.

---

# THE SCRIPT

## 0:00–0:40 — Opening (Member 1, Slide 1)

> Good morning, sir. We are a team of three, and our project is called
> **Indexed Product Search — a comparative study of database indexing**.
>
> We built a real product-search application on **100,000 products** in PostgreSQL.
> The user chooses a search method, and the application shows the **actual
> PostgreSQL execution time** and the **actual index used** for that query.
>
> I am **MEMBER 1**, and I worked on the data, schema, and indexes.
> **MEMBER 2** worked on the backend, parser, and search methods.
> **MEMBER 3** worked on the analysis dashboard, testing, and the live demo.

---

## 0:40–2:00 — Problem and goal (Member 1, Slides 2–3)

> In class, we learn indexes as diagrams: a B-tree splits, a hash bucket points to a
> row, the planner chooses a path. But we rarely see the same query run through
> different access paths on a real dataset, with real time and a real query plan.
>
> So our goal was simple: **make the database's behaviour visible.**
>
> We built one application where you can run the same query through seven methods:
>
> 1. Full table scan
> 2. B+ Tree
> 3. Hash index
> 4. Composite index
> 5. HNSW vector search
> 6. Hybrid search
> 7. Cached search
>
> The user selects the method manually. The application never chooses the “fastest”
> method for you. That is the point: we want to compare.
>
> Every number you will see comes from a real SQL execution. Nothing is hard-coded.
>
> We also group results by **query ID**, so the same query can be compared across
> every index you tried, and a different query gets a different graph.

---

## 2:00–3:15 — Tech stack and database connection (Member 1, Slide 4)

> Our stack is deliberately small and free.
>
> - **PostgreSQL 19** with the **pgvector** extension stores both the product rows
>   and the 384-dimensional embeddings.
> - **Python 3.12 + Flask** provides the API and the two web pages.
> - **psycopg 3** connects Flask to PostgreSQL through a **connection pool**.
> - **Sentence Transformers** runs a local model on CPU to turn text into vectors.
> - **Chart.js** draws the analysis graph in the browser.
>
> The connection is: browser → Flask → psycopg pool → PostgreSQL on port **5433**.
> The pool is opened once at startup, so every search does not pay the cost of a new
> database connection.
>
> The database URL is in `.env`:
> `postgresql://localhost:5433/product_search`.
>
> There are no paid APIs and no cloud services. After the model is downloaded once,
> the whole project runs offline.

---

## 3:15–5:30 — Dataset, schema, and seven indexes (Member 1, Slides 5–6)

> The dataset has **100,000 synthetic products**, exactly **10,000 in each of 10
> categories**. There are 45 brands, seven colours, prices from ₹501 to ₹279,993,
> ratings from 2.8 to 5.0, and **100,000 embeddings of 384 dimensions**.
>
> We validated the CSV before importing it: exact row count, unique product IDs,
> category distribution, no missing values, numeric ranges, no duplicates, and ID
> format. The report is in `data/dataset_validation.json`. The original CSV is never
> modified.
>
> The table is one wide `products` table. That is deliberate: this project compares
> **access paths**, not joins. A join would add cost that has nothing to do with the
> index comparison.
>
> Now the seven indexes — this is the heart of the project.
>
> | Index | Type | Columns | Size | Why |
> |---|---|---|---:|---|
> | `products_pkey` | B-tree | `product_id` | 4.3 MB | Row identity |
> | `idx_products_price_btree` | B-tree | `price_inr` | 4.0 MB | Price ranges |
> | `idx_products_category_btree` | B-tree | `category` | 1.7 MB | Category equality |
> | `idx_products_rating_btree` | B-tree | `rating` | 3.0 MB | Rating order/filter |
> | `idx_products_brand_hash` | Hash | `brand` | 6.4 MB | Brand equality |
> | `idx_products_category_price_color_btree` | Composite B-tree | `(category, price_inr, color)` | 10.2 MB | Category + price + colour |
> | `idx_products_embedding_hnsw` | HNSW | `embedding vector_cosine_ops` | 191.1 MB | Semantic search |
>
> All seven are valid and ready. We checked `indisvalid` and `indisready` in
> `pg_index`, and `/api/health` returns the live definitions.
>
> Why these choices?
>
> - **B-tree** for equality, ranges, and ordering. It is the general-purpose index.
> - **Hash** only for exact brand equality. It cannot do ranges or sorting.
> - **Composite** because the common query is category + price + colour. Category is
>   first because the leading-column rule requires it.
> - **HNSW** because semantic search needs a graph over vectors, not a sorted list.
>
> The HNSW index is **191 MB** — by far the most expensive index. That is a real
> trade-off: better semantic search, much more disk and build time.

---

## 5:30–7:30 — Architecture and end-to-end journey (Member 2, Slides 7–8)

> I am **MEMBER 2**. I built the backend: the parser, the SQL builder, the seven
> search modules, timing, and the cache.
>
> Here is the whole journey when you click **Search**.
>
> 1. The browser sends `POST /api/search` with four fields:
>    `query`, `method`, `limit`, and `include_plan`.
> 2. Flask validates them: the query must be text, the method must be one of the
>    seven, and the limit must be 5 or 10.
> 3. The parser converts the sentence into **structured filters**:
>    category, brand, colour, minimum/maximum price, use case, and keywords.
> 4. The **scope gate** checks whether the query belongs to the catalogue. If not,
>    it returns zero results in zero milliseconds and executes **no SQL**.
> 5. For HNSW and hybrid, the local model turns the query into a 384-dimensional
>    vector. Embedding time is measured separately.
> 6. The dispatcher sends the request to **exactly one** method module. There is no
>    automatic fallback to another method.
> 7. The SQL builder creates a parameterised query. Every user value is a `%s`
>    parameter — user text never becomes SQL text.
> 8. psycopg takes the SQL and values from the pool to PostgreSQL.
> 9. PostgreSQL's planner chooses the access path: Seq Scan, Bitmap Index Scan,
>    Index Scan, or the HNSW index.
> 10. Flask measures the database time, assembles the results, parsed filters,
>     warnings, and — if requested — the actual `EXPLAIN` plan.
> 11. The browser renders the cards and stores the measurement under a query ID.
>
> The important sentence is: **the planner decides the access path; we report what
> it actually did.** The method name is the question we ask the planner, not a
> command that forces a particular index.

---

## 7:30–9:15 — Parser, scope gate, and seven methods (Member 2, Slides 9–10)

> The parser is rule-based, not an LLM. It only extracts what is explicitly in the
> query. For example:
>
> `black laptop under 80000`
>
> becomes: category `Laptop`, colour `Black`, maximum price `80000`, no brand, no
> keywords. It never invents a filter.
>
> Before any method runs, the scope gate asks: does this query belong to the
> catalogue? It is in scope if it names a category or brand, or if every keyword
> actually appears in the product text. Colour and price alone are not enough.
>
> So `black laptop under 80000` is in scope. `flying car` is not: no category, no
> brand, no matching keyword. We return zero rows and zero database time. This is
> important because a vector index would otherwise return five random “nearest”
> products for nonsense.
>
> The seven methods are seven modules:
>
> - `full_scan` — same SQL, but index scans disabled, to create a baseline.
> - `btree` — normal relational SQL; the planner may use a B-tree.
> - `hash` — same SQL; the planner may use the brand hash index.
> - `composite_btree` — relational SQL ordered by price and colour, matching the
>   composite index.
> - `hnsw` — vector distance order, no structured filters.
> - `hybrid` — structured filters plus vector order, with pgvector iterative scan.
> - `cached` — a TTL/LRU cache in front of hybrid.
>
> The cache is not a database index. It stores result sets in application memory. A
> hit returns zero database time. A miss is a real hybrid query. That distinction is
> important.

---

## 9:15–10:30 — Why the timings are fair (Member 2, Slide 11)

> A benchmark is only useful if the measurement is honest. We did five things.
>
> First, we measure only around the actual SQL execution:
>
> ```python
> started = time.perf_counter()
> cur.execute(sql, params)
> rows = cur.fetchall()
> db_ms = (time.perf_counter() - started) * 1000
> ```
>
> Second, interactive searches send `include_plan: false`. `EXPLAIN ANALYZE` runs the
> query a second time, which would double the work and distort the time. Plans are
> still available through the API and tests.
>
> Third, the model and the indexes are warmed at startup. The first click does not
> pay a cold-start cost.
>
> Fourth, there is no hidden retry or keyword relaxation. One search executes one
> query.
>
> Fifth, the plan is captured separately and reported as `plan_capture_ms`, not added
> to `db_execution_ms`.
>
> The one intentional exception is the cache: a hit is supposed to be zero. We keep
> the miss sample too, so the cache story is complete.

---

## 10:30–16:30 — Live demo (Member 3, Slides 12–13)

> I am **MEMBER 3**. I built the analysis dashboard, the query IDs, the test suite,
> and I curated this demo. We will now run six queries. For each one, watch two
> things: the **database time** and the **query ID**.
>
> Our rule is simple: **the index must match the predicate.** If it does not match,
> PostgreSQL will not use it — or it will use it badly.

### Demo 1 — `wireless` (about 45 seconds)

**Click:** query `wireless`, limit 5, run **Full Table Scan**, then **B+ Tree**, then
**Hash**.

**Say:**

> There is no category, brand, colour, or price here — only a word that can appear
> anywhere in the text. All three methods take about **87–89 ms** and all three use a
> sequential scan. A B-tree cannot use a leading `%` wildcard, and a hash index
> cannot help at all. This is our control: when no index applies, every method
> becomes a scan. The times tie, and that is the correct result.

---

### Demo 2 — `laptop` (about 45 seconds)

**Click:** query `laptop`, run **Full Table Scan**, then **B+ Tree**.

**Say:**

> Now the query names a category. The full scan reads all 100,000 rows: about
> **10.5 ms**. The B+ Tree uses `idx_products_category_btree` and takes about
> **2.8 ms** — roughly 3.7 times faster.
>
> PostgreSQL uses a **bitmap index scan** here, because 10,000 rows — 10% of the
> table — match. It collects the row locations and reads the heap in physical order.
> The remaining cost is sorting the 10,000 rows by rating.
>
> This is the single-column B+ Tree doing its job. A composite index would be even
> faster; we will see that in query 4.

---

### Demo 3 — `Motorola` (about 60 seconds)

**Click:** query `Motorola`, run **Full Table Scan**, **Hash**, **Composite**,
**HNSW**, **Hybrid**.

**Say:**

> This is a brand equality. The full scan takes about **9 ms**. The hash index takes
> about **0.54 ms** — about 17 times faster.
>
> The plan shows `Bitmap Index Scan on idx_products_brand_hash` with condition
> `brand = 'Motorola'`. PostgreSQL hashes the value and goes straight to the 1,272
> Motorola rows. Then it sorts them by rating and returns five.
>
> Why is the composite method slower at about **1.1 ms**? The composite index starts
> with `category`, and this query has no category. The leading column is missing, so
> the composite index cannot be used. The planner falls back to the price index and
> filters brand while scanning prices. The hash index is the better match.
>
> Hash is perfect for equality, and useless for ranges or sorting. That is the
> trade-off.

---

### Demo 4 — `black laptop under 80000` (about 90 seconds)

**Click:** run **Full Table Scan**, **B+ Tree**, **Hash**, **Composite**, **HNSW**,
**Hybrid**. Then run **Cached** twice.

**Say:**

> This is the query our composite index was built for: category, colour, and a price
> limit. Only **373 rows** satisfy all three filters — 0.37% of the table.
>
> The full scan is about **9.8 ms**. B+ Tree and Hash are about **0.6 ms** each.
> Composite is about **0.12 ms** — roughly five times faster than the other
> relational methods and about 80 times faster than the full scan.
>
> Look at the plans. All three relational methods use the **same** composite index.
> The difference is the **order**. B+ Tree and Hash sort the 373 matches by rating.
> Composite orders by `price_inr, color, product_id`, which is exactly the index
> order, so PostgreSQL can walk the index and stop after five rows. No full sort.
>
> The index condition uses category and colour. Price is a filter, because price
> comes before colour in the index and a range would stop colour from being a tight
> boundary. This is a deliberate column-order trade-off.
>
> Now the cache: the first cached run is a miss at about **1.6 ms**; the second is a
> hit at **0.00 ms**. The cache is not an index. It simply remembers the result set.

---

### Demo 5 — `lightweight laptop for travel` (about 45 seconds)

**Click:** run **B+ Tree**, **Composite**, **HNSW**, **Hybrid**.

**Say:**

> The word **lightweight** appears **zero times** in our product text. The B+ Tree
> and composite index scan 10,000 laptops, find zero matches, and waste about
> **14–15 ms**.
>
> HNSW takes about **0.9 ms** and returns five laptops. It does not look for the
> word; it compares the meaning of the query with the meaning of the product. This
> is the trade-off: relational indexes are exact but literal; vector indexes are
> semantic but approximate. HNSW also ignores hard filters, which is why we built
> hybrid.

---

### Demo 6 — `Google pixel` (about 45 seconds)

**Click:** run **Hash**, **Composite**, **HNSW**, **Hybrid**.

**Say:**

> Here we combine a hard filter with semantic ranking. Hash and composite take about
> **1.1 ms**; HNSW takes about **0.8 ms**; hybrid takes about **0.7 ms**.
>
> Hybrid is the fastest and it guarantees that every result is a Google product. It
> walks the HNSW graph and keeps only rows where `brand = 'Google'`. HNSW happens to
> return Google Pixel phones because the query says Google, but it does not enforce
> the filter. Hybrid does.
>
> This is the best of both worlds when the user gives a brand and a meaning.

---

### Demo 7 — Analysis page and `flying car` (about 45 seconds)

**Click:** open **Analysis**. Point at the query cards. Click the first query, then
the `Google pixel` query. Then go back to Search and run `flying car`.

**Say:**

> Every query got its own ID. The first query has bars for the methods we ran; the
> `Google pixel` query has a different ID and a different graph. Clicking a card
> opens its graph without reloading the page.
>
> Finally, `flying car`: **zero results, zero milliseconds, no SQL**. The scope gate
> rejected it before the database was touched. A vector index would otherwise return
> five random neighbours. We chose to return an honest “not in this catalogue”.

---

## 16:30–17:30 — Analysis dashboard (Member 3, Slide 14)

> The analysis page is what turns this from a search demo into a measurement tool.
>
> The browser computes a stable query ID from the normalised query and the limit.
> The same query and limit always produce the same ID. Running the same query with a
> new method adds one bar to that query's graph. Changing the query creates a new ID
> and a new graph.
>
> The graph shows only the methods **we actually ran**. It does not guess or fill in
> missing bars. The table shows the database time, result count, cache status, and
> when it was measured.
>
> The graph deliberately uses **database execution time**, not embedding time. We are
> comparing index performance inside PostgreSQL. The API still reports embedding
> time separately, so the full end-to-end cost is available.
>
> Everything is stored in the browser's `localStorage`. It is a personal demo
> history, not a server-side benchmark table. Clearing browser storage clears it.

---

## 17:30–18:30 — Work division (All, Slide 15)

Each member speaks for about 20 seconds. Keep it specific.

**Member 1:**

> I own the data and database layer. I designed and validated the 100,000-row
> dataset, wrote the schema, chose the seven indexes and their column order, imported
> the data with `COPY`, generated the 384-dimensional embeddings, and verified that
> every index is valid and ready. My main DBMS decision was the index inventory:
> B-tree for ranges and ordering, hash for brand equality, composite for
> category + price + colour, and HNSW for semantic search.

**Member 2:**

> I own the backend and query engine. I wrote the parser that turns English into
> predicates, the scope gate, the shared SQL builder, all seven search modules, the
> timing wrapper, the connection pool, the cache, and the `EXPLAIN` capture. My main
> DBMS decisions were to measure only the real query, never hide the actual plan, and
> let the planner choose the access path instead of forcing an index.

**Member 3:**

> I own analysis, verification, and the demo. I built the query-specific analysis
> dashboard, the query IDs, the clickable history, and the 101-test suite. I curated
> the demo queries and checked every claimed index against the real `EXPLAIN` plan.
> My main contribution is proof: the tests, the plans, and the reproducible demo
> numbers.

---

## 18:30–19:20 — Testing, limitations, what we learned (Member 3, Slides 16–17)

> We have **101 passing tests** against the real database and the real model. They
> cover dataset integrity, the parser, all seven methods, index evidence, the scope
> gate, cache hit/miss/TTL/LRU, benchmark statistics, CSV export, validation errors,
> SQL-injection safety, and product details.
>
> We also verified the seven indexes directly in `pg_index`: all valid, all ready.
>
> We are honest about the limitations:
>
> - The dataset is synthetic, not real retail inventory.
> - HNSW is approximate; recall depends on its parameters.
> - `ILIKE '%keyword%'` cannot use a B-tree; a trigram/GIN index would be the right
>   tool for that workload.
> - The planner may choose a different index than the method name suggests. We report
>   what it actually did; that is intentional.
> - The cache is per-process and not shared.
> - The analysis history is browser-local.
> - Timings are warm, not cold-start.
>
> What we learned: **there is no “best index” in general.** There is only the index
> that matches the predicate, the column order, and the required ordering. The same
> database, the same data, and the same query can be 80 times faster or 80 times
> slower depending on that match.

---

## 19:20–20:00 — Conclusion (All, Slide 18)

**Member 1:**

> To conclude: we built a real PostgreSQL application with 100,000 products and
> seven indexes, and we made the database's decisions visible.

**Member 2:**

> We showed the full journey from a click to a plan: parser, scope gate, SQL,
> planner, execution, and response — with honest timing.

**Member 3:**

> And we proved it: 101 tests, real plans, and a query-specific analysis graph.
> Thank you, sir. We are happy to take questions.

---

# Quick answers for viva

**“Which index is fastest?”**
There is no single answer. For `Motorola`, hash is fastest. For
`black laptop under 80000`, composite is fastest. For `lightweight laptop for
travel`, HNSW is fastest. For `wireless`, no index helps and every method scans.

**“Why not always use the composite index?”**
It needs category as the leading column. `Motorola` has no category, so the
composite index cannot be used.

**“Why not always use hash?”**
Hash supports equality only. It cannot answer `price <= 80000`, cannot sort, and
cannot help a category.

**“Why does the B+ Tree method sometimes use the composite index?”**
Because the planner is free to choose any suitable index. The method name describes
the intended index family, not a restriction. We report the actual plan instead of
hiding that.

**“Why is the full scan not the slowest in query 1?”**
Because it is the only option. The B+ Tree and hash methods also fall back to a
sequential scan when no index applies, so the times tie. The ~88 ms is the cost of
reading 100,000 rows and running five `ILIKE` checks.

**“Why does the composite method beat B+ Tree on the same query?”**
Same index, different `ORDER BY`. Composite orders by price and colour, matching the
index, so it stops after five rows. B+ Tree and hash sort the matches by rating.

**“Why is HNSW fast on `lightweight`?”**
The word does not exist in the data. Relational indexes scan 10,000 laptops and find
zero. HNSW compares meaning and returns five neighbours.

**“Is HNSW exact?”**
No. It is approximate. Recall depends on `m`, `ef_construction`, and `ef_search`.

**“Why did hybrid beat HNSW on `Google pixel`?”**
Hybrid walks the HNSW graph and applies the brand filter, so it checks fewer
candidates. It is also guaranteed to return only Google products.

**“How do you prevent SQL injection?”**
Every user value is a `%s` parameter. SQL text is built only from fixed fragments.
The tests send an injection payload and confirm the table survives.

**“How do you know an index was used?”**
We read `EXPLAIN (ANALYZE, BUFFERS, VERBOSE, FORMAT JSON)` and report
`indexes_used`, node types, rows, and buffers. We also check `pg_index` validity.

**“What would you improve?”**
Add a GIN/trigram index for keyword search, measure HNSW recall, test concurrent
load, and move analysis history to a server-side store.

---

# If something goes wrong

| Problem | Fix |
|---|---|
| Database offline | `bash scripts/start_postgres.sh`, wait, refresh |
| Flask not running | `source .venv/bin/activate && python run.py` |
| Port 5001 busy | `lsof -tiTCP:5001 -sTCP:LISTEN \| xargs kill`, then start again |
| First semantic search slow | Model warm-up; wait a few seconds and repeat |
| Analysis graph empty | Run at least one in-scope search in this browser profile |
| Timings differ from this sheet | Normal; quote the order of magnitude and the plan, not the exact decimal |
| Wrong query card | Open `/analysis?q=Q-XXXXXX` with the ID shown on the result |
| Projector/browser fails | Use the backup screenshots and `docs/demo_query_results.json` |

---

# Rehearsal checklist

- [ ] Replace member names in the PPT and this script.
- [ ] Run the demo once end-to-end and note your machine's actual times.
- [ ] Clear analysis history before the real demo.
- [ ] Each member can explain the architecture and the seven methods without notes.
- [ ] Each member can answer the three questions for their own area.
- [ ] Member 3 can run the demo without reading the sheet.
- [ ] Member 1 can show `/api/health` and the seven indexes.
- [ ] Member 2 can show one `EXPLAIN` plan and explain it.
- [ ] Keep a backup of the demo numbers and screenshots.
- [ ] Finish within 20:00. Cut demo queries, not the conclusion.
