"""PostgreSQL access helpers.

All user supplied values are passed as query parameters. SQL strings are
constructed only from fixed fragments defined in the search modules.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterable, Iterator, Sequence

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .config import Config

_pool: ConnectionPool | None = None


def init_pool(database_url: str | None = None) -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            conninfo=database_url or Config.DATABASE_URL,
            min_size=1,
            max_size=10,
            timeout=10,
            kwargs={"row_factory": dict_row, "autocommit": True},
            open=True,
        )
    return _pool


def get_pool() -> ConnectionPool:
    return _pool or init_pool()


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


@contextmanager
def connection() -> Iterator[psycopg.Connection]:
    with get_pool().connection() as conn:
        yield conn


def fetch_all(sql: str, params: Sequence[Any] | None = None) -> list[dict[str, Any]]:
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            return list(cur.fetchall())


def fetch_one(sql: str, params: Sequence[Any] | None = None) -> dict[str, Any] | None:
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            return cur.fetchone()


def execute(sql: str, params: Sequence[Any] | None = None) -> None:
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())


def execute_many(sql: str, rows: Iterable[Sequence[Any]]) -> None:
    with connection() as conn:
        with conn.cursor() as cur:
            cur.executemany(sql, rows)


def table_exists(name: str = "products") -> bool:
    row = fetch_one(
        "SELECT to_regclass(%s) IS NOT NULL AS exists", (f"public.{name}",)
    )
    return bool(row and row["exists"])
