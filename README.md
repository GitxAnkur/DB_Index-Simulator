# Indexed Product Search & Database Performance Benchmarking System

**Product Search Engine: A Comparative Study of Database Indexing Techniques**

A full-stack DBMS academic project that compares seven database search and retrieval
techniques on exactly **100,000 synthetic products** using **PostgreSQL**, **pgvector**,
**Sentence Transformers**, **Flask**, and **Chart.js**.

The application is both a working natural-language product-search interface and a
measurement laboratory. Every timing shown in the UI comes from executing real
parameterised SQL against PostgreSQL; query plans come from
`EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)`.

![Landing page](docs/screenshots/01_landing.png)

## What is implemented

| Requirement | Status |
|---|---|
| 100,000-row dataset validation | Implemented; report at `docs/validation_report.md` |
| PostgreSQL schema + constraints | Implemented |
| pgvector + 384-dimensional embeddings | 100,000 real embeddings generated |
| HNSW vector index | Built (`m=16`, `ef_construction=64`) |
| Seven separately selectable methods | Implemented and tested |
| Natural-language parser | Categories, brands, colours, prices, use cases, keywords |
| Flask API | Search, benchmark, health, cache, CSV export |
| Frontend | Responsive search + benchmark dashboard with Chart.js |
| Repeated benchmark experiments | ≥ 5 repetitions, raw samples, statistics |
| EXPLAIN ANALYZE technical panel | SQL, plan tree, indexes, rows, buffers |
| CSV export | Per-run API export + fixed-suite CSV |
| Pytest suite | 86 tests passing against the real database |
| Documentation | README, setup, architecture, API, methods, methodology, report |

## Seven search methods

1. **Normal Search / Full Table Scan** — sequential-scan baseline with index and
   bitmap scans deliberately disabled for the measurement.
2. **B+ Tree Search** — PostgreSQL B-tree indexes on `price_inr`, `category`, and
   `rating`; equality and range predicates.
3. **Hash Index Search** — PostgreSQL hash index on `brand`; equality only. Queries
   without a brand explicitly report that the hash index is not applicable.
4. **Composite B+ Tree Search** — multicolumn B-tree on
   `(category, price_inr, color)`; demonstrates the leading-column rule.
5. **HNSW Vector Search** — cosine-distance approximate nearest-neighbour search
   over real Sentence Transformers embeddings.
6. **B+ Tree + HNSW Hybrid Search** — structured SQL filters combined with semantic
   ranking. The actual plan shows which indexes PostgreSQL used.
7. **Cached Search** — application-level TTL/LRU cache in front of hybrid search;
   demonstrates cache miss, hit, repeated queries, clearing, and separate hit timing.

The user must manually select the search method. The application never auto-selects
the “fastest” method.

## Technology stack

- **Frontend:** HTML, CSS, JavaScript, Chart.js 4.4.7 (vendored locally)
- **Backend:** Python 3.12, Flask 3.1
- **Database:** PostgreSQL 19 (Postgres.app build), pgvector 0.8.7
- **Embeddings:** `sentence-transformers/all-MiniLM-L6-v2` (384 dimensions, local CPU)
- **Data processing:** pandas, NumPy
- **Testing:** pytest
- **Cache:** in-process TTL + LRU cache (no Redis required)
- **Cost:** entirely free and open source; no paid APIs, hosting, or cloud services

## Project structure

```text
dbms_2/
├── app/
│   ├── __init__.py              # Flask application factory
│   ├── config.py                # Environment-driven configuration
│   ├── db.py                    # psycopg connection pool + parameterised helpers
│   ├── query_parser.py          # Rule-based natural-language parser
│   ├── embeddings.py            # Sentence Transformers service
│   ├── cache.py                 # Thread-safe TTL/LRU application cache
│   ├── plan.py                  # EXPLAIN JSON parser
│   ├── benchmark.py             # Repetition runner, statistics, CSV
│   ├── routes.py                # API endpoints
│   └── search/
│       ├── __init__.py          # Dispatcher and response assembly
│       ├── base.py              # Shared SQL/execution helpers
│       ├── full_scan.py         # Method 1
│       ├── btree.py             # Method 2
│       ├── hash_index.py        # Method 3
│       ├── composite_btree.py   # Method 4
│       ├── hnsw.py              # Method 5
│       ├── hybrid.py            # Method 6
│       └── cached.py            # Method 7
├── templates/index.html
├── static/
│   ├── css/style.css
│   ├── js/app.js
│   └── vendor/chart.umd.min.js
├── scripts/
│   ├── schema.sql
│   ├── validate_dataset.py
│   ├── init_db.py
│   ├── import_data.py
│   ├── generate_embeddings.py
│   ├── run_benchmarks.py
│   ├── start_postgres.sh
│   └── stop_postgres.sh
├── tests/                       # 86 pytest tests
├── data/                        # Validation and benchmark JSON
├── docs/                        # Reports, guides, CSV, screenshots
├── synthetic_products_100000.csv
├── requirements.txt
├── .env.example
├── pytest.ini
└── run.py
```

## Quick start (this machine)

The project is already initialised and the database contains 100,000 products and
100,000 embeddings. Start the local database and the web application:

```bash
# 1. Start PostgreSQL on port 5433 (data directory: .pgdata)
bash scripts/start_postgres.sh

# 2. Activate the prepared environment
source .venv/bin/activate

# 3. Start Flask
python run.py
```

Open **http://127.0.0.1:5001**.

The PostgreSQL binaries used here are from the free Postgres.app installation at
`~/Applications/Postgres.app/Contents/Versions/19/bin`. The helper script uses that
path by default; set `PGBIN` if PostgreSQL is installed elsewhere.

## Full setup from scratch

Requirements: Python 3.11/3.12, PostgreSQL 16+ with the pgvector extension, and
~1 GB of free disk space (dataset, table, embeddings, and HNSW index).

```bash
# Python environment
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env

# PostgreSQL (Postgres.app on macOS includes pgvector)
bash scripts/start_postgres.sh

# Validate the original CSV without modifying it
python scripts/validate_dataset.py

# Create schema, pgvector extension, and relational indexes
python scripts/init_db.py

# Bulk import all 100,000 rows with COPY
python scripts/import_data.py

# Generate 100,000 real embeddings and build the HNSW index
python scripts/generate_embeddings.py

# Run the fixed benchmark suite and write docs/benchmark_results.csv
python scripts/run_benchmarks.py --repetitions 5 --limit 10

# Start the app
python run.py
```

The first embedding run downloads the free `all-MiniLM-L6-v2` model from Hugging
Face and caches it locally. No API key is required.

### Rebuilding the database

`python scripts/init_db.py` drops and recreates the `products` table, so embeddings
must be regenerated afterwards:

```bash
python scripts/init_db.py
python scripts/import_data.py
python scripts/generate_embeddings.py
python scripts/run_benchmarks.py
```

## API summary

| Endpoint | Purpose |
|---|---|
| `POST /api/search` | Run one of the seven methods |
| `POST /api/benchmark` | Repeated measurements + statistics |
| `POST /api/benchmark/export` | Run a benchmark and download CSV |
| `GET /api/benchmark/suite` | Fixed seven-query suite |
| `GET /api/benchmark/results.csv` | Generated fixed-suite CSV |
| `GET /api/health` | App/database/dataset/embedding/index health |
| `GET /api/methods` | Method metadata |
| `GET /api/cache/stats` | Cache statistics |
| `POST /api/cache/clear` | Clear/invalidate the cache |
| `GET /api/products/<id>` | One product record |

Example:

```bash
curl -X POST http://127.0.0.1:5001/api/search \
  -H 'Content-Type: application/json' \
  -d '{"query":"black laptop under 80000","method":"composite_btree","limit":10}'
```

Full request/response documentation: `docs/api.md`.

## Benchmarks

Fixed suite (5 repetitions, Top 10, median database execution time in ms):

| Query | Full scan | B-tree | Hash | Composite | HNSW | Hybrid | Cached |
|---|---:|---:|---:|---:|---:|---:|---:|
| Samsung smartphone | 10.378 | 0.886 | 0.763 | 0.747 | 0.558 | 3.453 | 0.000 |
| Laptops | 11.504 | 2.641 | 2.489 | 2.689 | 0.547 | 0.514 | 0.000 |
| Laptop under 80000 | 9.839 | 1.711 | 1.599 | 1.609 | 0.700 | 0.658 | 0.000 |
| Black laptop under 80000 | 9.333 | 0.728 | 0.608 | 0.576 | 1.088 | 1.644 | 0.000 |
| Lightweight laptop for programming | 23.813 | 17.054 | 16.706 | 19.946 | 0.593 | 0.606 | 0.000 |
| Wireless headphones for travel | 15.783 | 20.600 | 20.666 | 22.073 | 0.597 | 0.577 | 0.000 |
| Gaming monitor under 30000 | 10.129 | 1.670 | 1.501 | 1.490 | 0.863 | 0.937 | 0.000 |

These are actual measurements from this machine, not hardcoded values. Full raw
samples are in `docs/benchmark_results.csv`; methodology is in
`docs/benchmark_methodology.md`. HNSW/hybrid database times exclude query-embedding
time (reported separately). Cached medians are zero because four of five runs are
cache hits; the first run is a real miss.

## Testing

```bash
source .venv/bin/activate
pytest -q
```

Result on this machine: **86 passed**. The suite exercises the real database:
dataset integrity, all seven methods, parser behaviour, result limits, invalid
requests, SQL parameterisation/injection safety, cache hit/miss/clear/TTL/LRU,
vector and hybrid search, benchmark statistics, CSV export, and API errors.

See `docs/testing.md`.

## Documentation

- `docs/installation.md` — full installation and execution guide
- `docs/database_setup.md` — schema, import, indexes, verification
- `docs/architecture.md` — system architecture and request flow
- `docs/api.md` — API reference
- `docs/search_methods.md` — seven methods and observed plans
- `docs/benchmark_methodology.md` — measurement methodology and validity
- `docs/testing.md` — test plan and results
- `docs/validation_report.md` — dataset validation
- `docs/benchmark_summary.md` — fixed-suite summary
- `docs/benchmark_results.csv` — raw fixed-suite samples
- `docs/report.md` — full academic report with actual results
- `docs/screenshots/` — application screenshots

## Dataset

`synthetic_products_100000.csv` contains exactly 100,000 synthetic products:
10 categories × 10,000 products, 45 brands, 7 colours, prices in INR, ratings
2.8–5.0, and stock 0–150. Product IDs range from `P000001` to `P100000`.
The original file is never modified; imports use UTF-8 BOM handling. Names are
intentionally non-unique; the primary key is `product_id`.

This is synthetic demonstration data, **not real retail inventory**.

## Known limitations

- The embedding model runs on CPU; the first semantic request in a fresh process
  may pay a one-time model-loading cost (the app warms the model in the background).
- HNSW is approximate; recall depends on `ef_search` and index parameters.
- Relational keyword search uses `ILIKE` and practical synonym expansion. When an
  exact keyword returns zero rows, the query is relaxed and the fallback is reported
  in the UI/API; semantic methods handle unseen vocabulary better.
- PostgreSQL’s planner may choose a different index than the method’s “expected”
  index. The actual plan is always displayed; no index usage is claimed without
  evidence.
- Cold-start measurements are not forced by restarting PostgreSQL; the benchmark
  uses one unmeasured warm-up run and reports cache conditions.
- Product images are intentionally postponed; `image_key` and `image_prompt` are
  preserved for future integration.
- Redis is optional and not required; the application cache is in-process and is
  therefore not shared across multiple Flask worker processes.
