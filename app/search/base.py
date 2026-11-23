"""Shared SQL construction and execution utilities for search methods."""
from __future__ import annotations

import time
from decimal import Decimal
from typing import Any, Sequence

from .. import db
from ..config import Config
from ..plan import parse_explain
from ..query_parser import ParsedQuery, keyword_condition

PRODUCT_COLUMNS = (
    "product_id, name, category, brand, price_inr, color, rating, "
    "stock_quantity, use_case, specifications, description, tags, "
    "image_key, image_prompt"
)

DEFAULT_ORDER = "rating DESC NULLS LAST, price_inr ASC, product_id ASC"


def structured_conditions(
    parsed: ParsedQuery, include_keywords: bool = True
) -> tuple[str, list[Any]]:
    """Build hard structured predicates.

    ``use_case`` is deliberately a soft ranking preference, not a hard filter:
    a user may ask for "programming" even when no product in that category has
    that exact use-case label. The parser still extracts and displays it.
    """
    clauses: list[str] = []
    params: list[Any] = []

    if parsed.category:
        clauses.append("category = %s")
        params.append(parsed.category)
    if parsed.brand:
        clauses.append("brand = %s")
        params.append(parsed.brand)
    if parsed.color:
        clauses.append("color = %s")
        params.append(parsed.color)
    if parsed.min_price is not None:
        clauses.append("price_inr >= %s")
        params.append(parsed.min_price)
    if parsed.max_price is not None:
        clauses.append("price_inr <= %s")
        params.append(parsed.max_price)
    if include_keywords and parsed.keywords:
        keyword_sql, keyword_params = keyword_condition(parsed.keywords)
        clauses.append(keyword_sql)
        params.extend(keyword_params)

    return (" AND ".join(clauses) if clauses else "TRUE"), params


def order_by(parsed: ParsedQuery) -> tuple[str, list[Any]]:
    """Rank matching use cases first without excluding non-matching products."""
    if parsed.use_case:
        return (
            "(use_case = %s) DESC NULLS LAST, " + DEFAULT_ORDER,
            [parsed.use_case],
        )
    return DEFAULT_ORDER, []


def relational_sql(parsed: ParsedQuery, limit: int) -> tuple[str, list[Any]]:
    where_sql, params = structured_conditions(parsed, include_keywords=True)
    order_sql, order_params = order_by(parsed)
    sql = (
        f"SELECT {PRODUCT_COLUMNS} FROM products WHERE {where_sql} "
        f"ORDER BY {order_sql} LIMIT %s"
    )
    return sql, [*params, *order_params, limit]


def execute_relational(
    parsed: ParsedQuery,
    limit: int,
    include_plan: bool,
    settings: Sequence[str] = (),
) -> dict[str, Any]:
    """Execute a relational query, relaxing keyword filters only if the exact
    query returns no rows. The fallback is recorded in the response so the
    benchmark never silently changes semantics.
    """
    sql, params = relational_sql(parsed, limit)
    outcome = execute_sql(sql, params, settings, include_plan)
    outcome["sql"] = sql
    outcome["params"] = params
    outcome["fallback"] = None

    if not outcome["rows"] and parsed.keywords:
        relaxed = ParsedQuery(
            original_query=parsed.original_query,
            normalized_query=parsed.normalized_query,
            category=parsed.category,
            brand=parsed.brand,
            color=parsed.color,
            min_price=parsed.min_price,
            max_price=parsed.max_price,
            use_case=parsed.use_case,
            keywords=[],
            price_expression=parsed.price_expression,
            matched_terms=parsed.matched_terms,
        )
        relaxed_sql, relaxed_params = relational_sql(relaxed, limit)
        relaxed_outcome = execute_sql(
            relaxed_sql, relaxed_params, settings, include_plan
        )
        if relaxed_outcome["rows"]:
            relaxed_outcome["db_execution_ms"] = round(
                outcome["db_execution_ms"]
                + relaxed_outcome["db_execution_ms"],
                3,
            )
            relaxed_outcome["sql"] = relaxed_sql
            relaxed_outcome["params"] = relaxed_params
            relaxed_outcome["fallback"] = {
                "relaxed": "keywords",
                "original_keywords": parsed.keywords,
                "original_sql": sql,
                "original_params": params,
                "original_db_execution_ms": outcome["db_execution_ms"],
                "note": (
                    "The exact keyword filter returned zero rows, so the keyword "
                    "predicate was relaxed and the category/price/brand/colour "
                    "filters were retained. This fallback is included in the "
                    "reported database time."
                ),
            }
            return relaxed_outcome
    return outcome


def serialise_rows(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for row in rows:
        item = {}
        for key, value in row.items():
            if isinstance(value, Decimal):
                item[key] = float(value)
            else:
                item[key] = value
        result.append(item)
    return result


def _plan_settings(settings: Sequence[str]) -> None:
    # Settings are fixed strings defined by the search modules, never user input.
    for statement in settings:
        db.execute(statement)


def execute_sql(
    sql: str,
    params: Sequence[Any],
    settings: Sequence[str] = (),
    include_plan: bool = True,
) -> dict[str, Any]:
    """Execute a parameterised query and optionally capture EXPLAIN ANALYZE.

    The reported db_execution_ms covers the actual result query. EXPLAIN
    ANALYZE is a separate execution used only for technical inspection, so its
    cost is reported separately as plan_capture_ms.
    """
    rows: list[dict[str, Any]] = []
    db_ms = 0.0
    plan = None
    plan_capture_ms = 0.0
    explain_error = None

    with db.connection() as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                for statement in settings:
                    cur.execute(statement)

                started = time.perf_counter()
                cur.execute(sql, list(params))
                rows = list(cur.fetchall())
                db_ms = (time.perf_counter() - started) * 1000

                if include_plan:
                    plan_started = time.perf_counter()
                    try:
                        cur.execute(
                            "EXPLAIN (ANALYZE, BUFFERS, VERBOSE, FORMAT JSON) " + sql,
                            list(params),
                        )
                        explain_row = cur.fetchone()
                        explain_json = explain_row["QUERY PLAN"] if explain_row else None
                        plan = parse_explain(explain_json)
                    except Exception as exc:  # pragma: no cover - defensive
                        explain_error = str(exc)
                    plan_capture_ms = (time.perf_counter() - plan_started) * 1000

    return {
        "rows": serialise_rows(rows),
        "db_execution_ms": round(db_ms, 3),
        "plan": plan,
        "plan_capture_ms": round(plan_capture_ms, 3),
        "explain_error": explain_error,
    }


def vector_settings() -> list[str]:
    return [f"SET LOCAL hnsw.ef_search = {int(Config.HNSW_EF_SEARCH)}"]


def vector_info(embedding_dim: int = Config.EMBEDDING_DIM) -> dict[str, Any]:
    return {
        "extension": "pgvector",
        "index": "idx_products_embedding_hnsw",
        "index_type": "HNSW",
        "metric": "cosine",
        "operator": "<=>",
        "distance_formula": "cosine_distance = 1 - cosine_similarity",
        "dimension": embedding_dim,
        "ef_search": Config.HNSW_EF_SEARCH,
        "model": Config.EMBEDDING_MODEL,
    }


def similarity_expression() -> str:
    return "1 - (embedding <=> %s::vector) AS similarity"
