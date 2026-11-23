# Installation and Execution Guide

This project runs entirely locally with free and open-source software. No API keys,
paid database, paid hosting, or cloud service are required.

## 1. Prerequisites

| Component | Tested version | Notes |
|---|---|---|
| Python | 3.12.16 | 3.11+ should work |
| PostgreSQL | 19.0 | 16+ supported; pgvector required |
| pgvector | 0.8.7 | Included with Postgres.app 3.0 |
| Sentence Transformers | 6.3.0 | Model downloaded from Hugging Face |
| Disk | ~1 GB free | CSV 61 MB, table 86 MB, HNSW 191 MB, indexes |
| RAM | 4 GB+ recommended | Embedding generation uses CPU |

### macOS: free PostgreSQL with pgvector

The project was developed with the free **Postgres.app** distribution, which bundles
PostgreSQL and pgvector. Download it from <https://postgresapp.com/> and install the
app (a user-level copy in `~/Applications` is sufficient). The helper script uses:

```text
~/Applications/Postgres.app/Contents/Versions/19/bin
```

If your Postgres.app version directory differs, set `PGBIN`:

```bash
export PGBIN="$HOME/Applications/Postgres.app/Contents/Versions/17/bin"
```

### Linux / other PostgreSQL installations

Install PostgreSQL 16+ and the pgvector extension using your package manager, then
point `PGBIN` at the `bin` directory and set `DATABASE_URL` in `.env`. Example
(Debian/Ubuntu):

```bash
sudo apt install postgresql postgresql-contrib postgresql-16-pgvector
```

Create a database named `product_search` and enable the extension:

```sql
CREATE DATABASE product_search;
\c product_search
CREATE EXTENSION vector;
```

## 2. Python environment

From the project root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

The `requirements.txt` pins the versions used during development.

## 3. Environment variables

`.env.example`:

```dotenv
DATABASE_URL=postgresql://localhost:5433/product_search
EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
EMBEDDING_DIM=384
FLASK_HOST=127.0.0.1
FLASK_PORT=5001
FLASK_DEBUG=0
CACHE_TTL_SECONDS=300
CACHE_MAX_ENTRIES=512
DATASET_PATH=synthetic_products_100000.csv
```

The local database uses trust authentication on localhost port 5433. Do not reuse
these settings for a network-exposed deployment.

## 4. Start PostgreSQL

```bash
bash scripts/start_postgres.sh
```

The script:

1. Locates the PostgreSQL binaries.
2. Runs `initdb` into the project’s `.pgdata` directory if needed.
3. Starts the server on port 5433 with a project-local socket directory.
4. Creates the `product_search` database if it does not exist.

Check:

```bash
$PGBIN/psql -h localhost -p 5433 -d product_search -c "SELECT version();"
```

Stop the server with:

```bash
bash scripts/stop_postgres.sh
```

## 5. Build the database

Run these steps in order:

```bash
# Validate the CSV (read-only)
python scripts/validate_dataset.py

# Create the products table, pgvector extension, and relational indexes
python scripts/init_db.py

# Bulk import 100,000 rows
python scripts/import_data.py

# Generate embeddings and build the HNSW index
python scripts/generate_embeddings.py
```

Expected output from the import step:

```text
Validation passed: 100,000 rows
Imported 100,000 products in 1.05s
  Camera               10,000
  Gaming Accessories   10,000
  ...
Embeddings currently present: 0
```

Expected output from the embedding step:

```text
Model: sentence-transformers/all-MiniLM-L6-v2 (384 dimensions)
Products needing embeddings: 100,000
...
Embeddings present: 100,000/100,000
Building HNSW index (m=16, ef_construction=64)...
HNSW index built in ~17s
```

The embedding step takes several minutes on CPU (about 350 products/s on the
development machine). It is resumable: only products with `embedding IS NULL` are
processed. Use `--rebuild` to recompute everything, or `--limit N` only for a
development subset (the full project requires all 100,000).

## 6. Run the application

```bash
source .venv/bin/activate
python run.py
```

Open <http://127.0.0.1:5001>.

The app warms the Sentence Transformers model in a background thread at startup so
the first semantic search normally does not pay the full model-loading cost.

## 7. Run the benchmark suite

```bash
python scripts/run_benchmarks.py --repetitions 5 --limit 10
```

This writes:

- `docs/benchmark_results.csv` — one row per raw sample
- `docs/benchmark_summary.md` — median comparison table
- `data/benchmark_results.json` — complete results, plans, statistics

## 8. Run the tests

```bash
pytest -q
```

The tests require the database to be populated with 100,000 products and embeddings.
They are integration tests against the real local database, not mocks.

## 9. Troubleshooting

**`psql: command not found`** — use `$PGBIN/psql` or add the PostgreSQL `bin`
directory to `PATH`. `scripts/start_postgres.sh` does not modify your shell PATH.

**`extension "vector" is not available`** — install pgvector for your PostgreSQL
version. Postgres.app 3.0 includes it. Verify with:

```sql
SELECT * FROM pg_available_extensions WHERE name = 'vector';
```

**Port 5433 already in use** — change `PGPORT` for the helper script and
`DATABASE_URL` in `.env`, then restart.

**Model download fails** — ensure internet access for the first run. The model is
cached under `~/.cache/huggingface`. The app itself runs offline afterwards.

**HNSW index build is slow / memory heavy** — the build uses
`maintenance_work_mem = 512MB`. Lower it if necessary; the index still builds.

**First semantic query is slow** — the model may still be loading, or the PostgreSQL
buffer cache is cold. Run the query again. The UI reports database time separately
from embedding time.

**Planner does not use the expected index** — this is reported honestly in the
technical panel. The planner may choose a sequential scan when a predicate is not
selective, or choose a different B-tree/composite index. See
`docs/search_methods.md`.

## 10. Reset

```bash
bash scripts/stop_postgres.sh
rm -rf .pgdata .pglog
bash scripts/start_postgres.sh
python scripts/init_db.py
python scripts/import_data.py
python scripts/generate_embeddings.py
python scripts/run_benchmarks.py
```

Do not delete `synthetic_products_100000.csv`; it is the fixed input dataset.
