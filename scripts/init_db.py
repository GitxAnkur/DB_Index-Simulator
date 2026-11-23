#!/usr/bin/env python3
"""Create the PostgreSQL schema, pgvector extension and relational indexes."""
from __future__ import annotations

import sys
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import Config  # noqa: E402

SCHEMA = ROOT / "scripts" / "schema.sql"


def main() -> None:
    sql = SCHEMA.read_text(encoding="utf-8")
    with psycopg.connect(Config.DATABASE_URL, autocommit=True, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            cur.execute("ANALYZE products")
            cur.execute(
                "SELECT count(*) AS n FROM pg_indexes WHERE tablename='products'"
            )
            indexes = cur.fetchone()["n"]
            cur.execute("SELECT extversion FROM pg_extension WHERE extname='vector'")
            vector_version = cur.fetchone()["extversion"]
    print(f"Schema created. pgvector={vector_version}, indexes={indexes}")


if __name__ == "__main__":
    main()
