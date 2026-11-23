#!/usr/bin/env python3
"""Generate real Sentence Transformers embeddings for all products and build
the pgvector HNSW index.

Embedding document = name | category | brand | use_case | specifications |
description | tags | colour. Vectors are L2-normalised, so cosine distance is
used by the HNSW index.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import psycopg
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import Config  # noqa: E402
from app.embeddings import encode_texts, get_model, product_embedding_text, to_pgvector  # noqa: E402

FIELDS = (
    "product_id, name, category, brand, use_case, specifications, "
    "description, tags, color"
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-size", type=int, default=512)
    parser.add_argument("--limit", type=int, default=None, help="Development only")
    parser.add_argument("--rebuild", action="store_true", help="Recompute every embedding")
    parser.add_argument("--skip-index", action="store_true")
    args = parser.parse_args()

    model = get_model()
    dimension = int(model.get_sentence_embedding_dimension())
    if dimension != Config.EMBEDDING_DIM:
        raise SystemExit(
            f"Model dimension {dimension} does not match schema dimension "
            f"{Config.EMBEDDING_DIM}. Update the schema and EMBEDDING_DIM."
        )
    print(f"Model: {Config.EMBEDDING_MODEL} ({dimension} dimensions)")

    with psycopg.connect(Config.DATABASE_URL, autocommit=True, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            if args.rebuild:
                cur.execute("UPDATE products SET embedding = NULL")
            if not args.skip_index:
                cur.execute("DROP INDEX IF EXISTS idx_products_embedding_hnsw")
            cur.execute(
                f"SELECT {FIELDS} FROM products WHERE embedding IS NULL "
                "ORDER BY product_id"
            )
            rows = cur.fetchall()
            if args.limit:
                rows = rows[: args.limit]
            print(f"Products needing embeddings: {len(rows):,}")
            if not rows:
                print("All products already have embeddings.")
            else:
                cur.execute(
                    "CREATE UNLOGGED TABLE IF NOT EXISTS embedding_staging ("
                    "product_id VARCHAR(10) PRIMARY KEY, "
                    "embedding VECTOR(%s))" % dimension
                )
                started = time.perf_counter()
                total = 0
                for start in range(0, len(rows), args.batch_size):
                    batch = rows[start : start + args.batch_size]
                    texts = [product_embedding_text(row) for row in batch]
                    vectors = encode_texts(texts, batch_size=min(128, args.batch_size))
                    if vectors.shape[1] != dimension:
                        raise SystemExit("Embedding dimension changed unexpectedly")
                    cur.execute("TRUNCATE embedding_staging")
                    with cur.copy(
                        "COPY embedding_staging (product_id, embedding) FROM STDIN"
                    ) as copy:
                        for row, vector in zip(batch, vectors):
                            copy.write_row((row["product_id"], to_pgvector(vector)))
                    cur.execute(
                        "UPDATE products p SET embedding = s.embedding "
                        "FROM embedding_staging s "
                        "WHERE p.product_id = s.product_id"
                    )
                    total += len(batch)
                    elapsed = time.perf_counter() - started
                    rate = total / elapsed if elapsed else 0
                    print(
                        f"  embedded {total:,}/{len(rows):,} "
                        f"({rate:.1f} products/s, {elapsed:.1f}s)",
                        flush=True,
                    )
                cur.execute("DROP TABLE IF EXISTS embedding_staging")
                print(f"Embeddings generated in {time.perf_counter() - started:.1f}s")

            cur.execute(
                "SELECT count(*) AS total, count(embedding) AS embedded FROM products"
            )
            counts = cur.fetchone()
            print(
                f"Embeddings present: {counts['embedded']:,}/{counts['total']:,}"
            )

            if not args.skip_index and counts["embedded"] == counts["total"]:
                print("Building HNSW index (m=16, ef_construction=64)...")
                cur.execute("SET maintenance_work_mem = '512MB'")
                index_started = time.perf_counter()
                cur.execute(
                    "CREATE INDEX idx_products_embedding_hnsw "
                    "ON products USING hnsw (embedding vector_cosine_ops) "
                    "WITH (m = 16, ef_construction = 64)"
                )
                print(
                    f"HNSW index built in {time.perf_counter() - index_started:.1f}s"
                )
            cur.execute("ANALYZE products")
            cur.execute(
                "SELECT pg_size_pretty(pg_relation_size('products')) AS table_size"
            )
            sizes = cur.fetchone()
            if not args.skip_index:
                cur.execute(
                    "SELECT pg_size_pretty(pg_relation_size("
                    "'idx_products_embedding_hnsw')) AS hnsw_size"
                )
                sizes.update(cur.fetchone())
            print(sizes)


if __name__ == "__main__":
    main()
