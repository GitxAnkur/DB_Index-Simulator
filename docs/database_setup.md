# Database Setup and Schema

This document describes the physical database design, the import pipeline, every
index, and the verification queries used to confirm that the database matches the
100,000-row source dataset.

## 1. Environment

| Item | Value |
|---|---|
| PostgreSQL | 19.0 (Postgres.app build) |
| pgvector | 0.8.7 |
| Database | `product_search` |
| Host / port | `localhost` / `5433` |
| Data directory | `<project>/.pgdata` (project-local cluster) |
| Authentication | `trust` on localhost only |
| Connection URL | `postgresql://localhost:5433/product_search` |

The project uses a dedicated cluster instead of a system-wide PostgreSQL service so
that the experiment is reproducible and cannot disturb other databases on the
machine. `scripts/start_postgres.sh` initialises the cluster on first use, starts it
on port 5433, and creates the `product_search` database if necessary.

```bash
bash scripts/start_postgres.sh
bash scripts/stop_postgres.sh
```

## 2. Table definition

`scripts/schema.sql` creates the extension and the single `products` table:

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE products (
    product_id       VARCHAR(10) PRIMARY KEY,
    name             TEXT        NOT NULL,
    category         TEXT        NOT NULL,
    brand            TEXT        NOT NULL,
    price_inr        NUMERIC(12, 2) NOT NULL CHECK (price_inr >= 0),
    color            TEXT,
    rating           NUMERIC(2, 1) CHECK (rating >= 0 AND rating <= 5),
    stock_quantity   INTEGER     NOT NULL CHECK (stock_quantity >= 0),
    use_case         TEXT,
    specifications   TEXT,
    description      TEXT,
    tags             TEXT,
    image_key        TEXT,
    image_prompt     TEXT,
    embedding        VECTOR(384)
);
```

Design notes:

- `product_id` is the natural business key (`P000001` … `P100000`) and the primary
  key. Product **names are intentionally non-unique** in the source dataset; only the
  ID is unique.
- `price_inr` is `NUMERIC(12,2)` so currency arithmetic is exact. The benchmark
  parameter is passed as a Python float and PostgreSQL casts it for comparison.
- `rating` is constrained to the source range 0–5; the actual data is 2.8–5.0.
- `stock_quantity` is a non-negative integer.
- `specifications` and `tags` are stored as text (the source encodes lists as JSON
  strings / comma-separated text). They are searched with `ILIKE`.
- `embedding` is `VECTOR(384)` because `all-MiniLM-L6-v2` produces 384 dimensions.
  It is nullable so import can complete before the embedding job runs.
- `image_key` and `image_prompt` are preserved verbatim. Images are intentionally
  postponed in this version.

## 3. Index inventory

| Index | Type | Columns | Purpose |
|---|---|---|---|
| `products_pkey` | B-tree (primary key) | `product_id` | Row identity |
| `idx_products_price_btree` | B-tree | `price_inr` | Range predicates (method 2) |
| `idx_products_category_btree` | B-tree | `category` | Equality predicates (method 2) |
| `idx_products_rating_btree` | B-tree | `rating` | Equality/range and ordering support (method 2) |
| `idx_products_brand_hash` | Hash | `brand` | Equality only (method 3) |
| `idx_products_category_price_color_btree` | B-tree (composite) | `(category, price_inr, color)` | Multi-predicate queries (method 4) |
| `idx_products_embedding_hnsw` | HNSW (`vector_cosine_ops`) | `embedding` | Approximate nearest neighbour (method 5) |

The HNSW index is **not** created by `schema.sql`. It is created by
`scripts/generate_embeddings.py` after all vectors exist, because building an HNSW
index incrementally during a 100,000-row bulk load is much slower. Parameters:

```sql
SET maintenance_work_mem = '512MB';
CREATE INDEX idx_products_embedding_hnsw
    ON products USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);
```

At query time each vector method runs `SET LOCAL hnsw.ef_search = 100`.

### Measured storage (this machine)

| Object | Size |
|---|---:|
| `products` table total (heap + indexes + TOAST) | 465 MB |
| Heap only | 86 MB |
| HNSW index | 191 MB |
| Composite B-tree | 10 MB |
| Brand hash index | 6.4 MB |
| Primary key | 4.4 MB |
| Price B-tree | 4.1 MB |
| Rating B-tree | 3.1 MB |
| Category B-tree | 1.7 MB |

## 4. Import pipeline

Run in this order:

```bash
python scripts/validate_dataset.py   # read-only validation, writes data/dataset_validation.json
python scripts/init_db.py            # drops/recreates products, enables pgvector, creates indexes
python scripts/import_data.py        # COPY of all 100,000 rows
python scripts/generate_embeddings.py # 100,000 embeddings + HNSW build
```

### Validation

`validate_dataset.py` reads `synthetic_products_100000.csv` with `utf-8-sig`
(the file has a UTF-8 BOM), never writes to it, and checks:

1. exactly 100,000 rows;
2. unique product IDs and complete `P000001`–`P100000` range;
3. exactly 10 categories, 10,000 each;
4. no missing values in any column;
5. numeric, non-negative prices;
6. ratings within 0–5;
7. non-negative stock;
8. no duplicate full records;
9. product-ID format.

All checks pass; see `docs/validation_report.md`.

### Bulk import

`import_data.py` uses PostgreSQL `COPY ... FROM STDIN` inside one transaction. This
is substantially faster than 100,000 individual `INSERT` statements. The CSV header
is mapped explicitly to table columns, and `embedding` is left `NULL`.

```text
Imported 100,000 products in ~1.05 s
```

### Embeddings

`generate_embeddings.py`:

1. loads `sentence-transformers/all-MiniLM-L6-v2` on CPU;
2. builds a document string from name, category, brand, use case, description,
   tags, and specifications;
3. encodes in batches (default 256, configurable with `--batch-size`);
4. normalises vectors and writes them with `UPDATE ... WHERE product_id = %s`;
5. is resumable (`WHERE embedding IS NULL`) and supports `--rebuild` and `--limit`;
6. builds the HNSW index when all vectors are present.

On the development machine encoding ran at roughly 350 products/second, so the full
job takes several minutes.

## 5. Verification queries

### Row and embedding counts

```sql
SELECT count(*) AS products,
       count(embedding) AS embedded,
       count(DISTINCT category) AS categories
FROM products;
```

Expected: `100000 | 100000 | 10`.

### Category distribution

```sql
SELECT category, count(*)
FROM products
GROUP BY category
ORDER BY category;
```

Every category returns 10,000.

### Embedding dimensions

```sql
SELECT min(vector_dims(embedding)) AS min_dim,
       max(vector_dims(embedding)) AS max_dim
FROM products;
```

Expected: `384 | 384`.

### Index definitions

```sql
SELECT indexname, indexdef
FROM pg_indexes
WHERE schemaname = 'public' AND tablename = 'products'
ORDER BY indexname;
```

The pytest suite asserts the presence of all six named indexes plus the primary key,
and asserts `USING hash` for the brand index and `USING hnsw` /
`vector_cosine_ops` for the vector index.

### Extension version

```sql
SELECT extversion FROM pg_extension WHERE extname = 'vector';
```

Expected: `0.8.7`.

### Plan sanity check

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM products
WHERE category = 'Laptop' AND color = 'Black' AND price_inr <= 80000
ORDER BY rating DESC NULLS LAST, price_inr ASC, product_id ASC
LIMIT 10;
```

The actual plan is displayed in the application’s technical panel and stored in
`data/benchmark_results.json`. No index usage is claimed unless it appears there.

## 6. Rebuilding

`init_db.py` drops and recreates `products`, so a rebuild always requires re-import
and re-embedding:

```bash
python scripts/init_db.py
python scripts/import_data.py
python scripts/generate_embeddings.py
python scripts/run_benchmarks.py --repetitions 5 --limit 10
```

The source CSV is never modified.
