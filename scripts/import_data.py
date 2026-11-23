#!/usr/bin/env python3
"""Bulk import the validated CSV into PostgreSQL using COPY.

All 14 original fields are preserved. Embeddings are generated separately so
that vector index construction can be measured and retried independently.
"""
from __future__ import annotations

import argparse
import math
import sys
import time
from pathlib import Path

import pandas as pd
import psycopg
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import Config  # noqa: E402
from scripts.validate_dataset import DEFAULT_CSV, validate  # noqa: E402

COLUMNS = [
    "product_id",
    "name",
    "category",
    "brand",
    "price_inr",
    "color",
    "rating",
    "stock_quantity",
    "use_case",
    "specifications",
    "description",
    "tags",
    "image_key",
    "image_prompt",
]


def clean(value):
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--skip-validation", action="store_true")
    args = parser.parse_args()

    if not args.skip_validation:
        report = validate(args.csv)
        if not report["all_checks_passed"]:
            failed = [k for k, v in report["checks"].items() if not v]
            raise SystemExit(f"Refusing to import invalid dataset: {failed}")
        print(f"Validation passed: {report['rows']:,} rows")

    df = pd.read_csv(args.csv, encoding="utf-8-sig")
    missing = [c for c in COLUMNS if c not in df.columns]
    if missing:
        raise SystemExit(f"Missing columns: {missing}")

    copy_sql = (
        f"COPY products ({', '.join(COLUMNS)}) FROM STDIN "
        "WITH (FORMAT text, NULL '\\N')"
    )

    started = time.perf_counter()
    with psycopg.connect(Config.DATABASE_URL, autocommit=True, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE products")
            with cur.copy(copy_sql) as copy:
                for row in df[COLUMNS].itertuples(index=False, name=None):
                    copy.write_row(tuple(clean(v) for v in row))
            cur.execute("ANALYZE products")
            cur.execute("SELECT count(*) AS n FROM products")
            count = cur.fetchone()["n"]
            cur.execute(
                "SELECT category, count(*) AS n FROM products "
                "GROUP BY category ORDER BY category"
            )
            categories = cur.fetchall()
            cur.execute("SELECT count(*) AS n FROM products WHERE embedding IS NOT NULL")
            embedded = cur.fetchone()["n"]
    elapsed = time.perf_counter() - started

    print(f"Imported {count:,} products in {elapsed:.2f}s")
    for row in categories:
        print(f"  {row['category']:<20} {row['n']:,}")
    print(f"Embeddings currently present: {embedded:,}")
    if count != 100_000:
        raise SystemExit(f"Expected 100,000 rows, got {count}")


if __name__ == "__main__":
    main()
