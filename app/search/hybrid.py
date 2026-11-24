"""Method 5: hybrid relational + HNSW vector search.

Structured predicates (category, brand, colour, price, use case) are applied
in SQL together with cosine-distance ordering. The actual plan determines
whether the relational index, the HNSW index, or both were used; this module
never claims index usage that the plan does not show.
"""
from __future__ import annotations

import numpy as np

from ..embeddings import to_pgvector
from ..query_parser import ParsedQuery
from .base import (
    PRODUCT_COLUMNS,
    execute_sql,
    filtered_vector_settings,
    similarity_expression,
    vector_info,
)

METHOD = "hybrid"
LABEL = "Hybrid (Filters + Vector)"
DESCRIPTION = (
    "Combines structured relational filters with semantic similarity. "
    "Structured predicates are evaluated by PostgreSQL while the embedding "
    "ranks the remaining candidates."
)
EXPECTED_INDEX = "relational indexes + idx_products_embedding_hnsw"


def search(
    parsed: ParsedQuery,
    limit: int,
    include_plan: bool = True,
    query_embedding: np.ndarray | None = None,
) -> dict:
    if query_embedding is None:
        raise ValueError("Hybrid search requires a query embedding")
    vector = to_pgvector(query_embedding)

    clauses = ["embedding IS NOT NULL"]
    params: list[object] = []
    filters: dict[str, object] = {}
    if parsed.category:
        clauses.append("category = %s")
        params.append(parsed.category)
        filters["category"] = parsed.category
    if parsed.brand:
        clauses.append("brand = %s")
        params.append(parsed.brand)
        filters["brand"] = parsed.brand
    if parsed.color:
        clauses.append("color = %s")
        params.append(parsed.color)
        filters["color"] = parsed.color
    if parsed.min_price is not None:
        clauses.append("price_inr >= %s")
        params.append(parsed.min_price)
        filters["min_price"] = parsed.min_price
    if parsed.max_price is not None:
        clauses.append("price_inr <= %s")
        params.append(parsed.max_price)
        filters["max_price"] = parsed.max_price

    where_sql = " AND ".join(clauses)
    sql = (
        f"SELECT {PRODUCT_COLUMNS}, {similarity_expression()} "
        f"FROM products WHERE {where_sql} "
        "ORDER BY embedding <=> %s::vector LIMIT %s"
    )
    outcome = execute_sql(
        sql, [vector, *params, vector, limit], filtered_vector_settings(), include_plan
    )
    outcome.update(
        {
            "sql": sql,
            "params": [
                f"<{len(query_embedding)}-dim query vector>",
                *params,
                f"<{len(query_embedding)}-dim query vector>",
                limit,
            ],
            "planner_settings": [
                f"hnsw.ef_search = {vector_info()['ef_search']}",
                "hnsw.iterative_scan = relaxed_order",
            ],
            "method_details": {
                "search_type": "structured filters + HNSW semantic ranking",
                "structured_filters": filters,
                "structured_filter_count": len(filters),
                "semantic_use_case_hint": parsed.use_case,
                "semantic_query": parsed.original_query,
                "note": (
                    "PostgreSQL decides whether to use a relational index, the "
                    "HNSW index, or both. Iterative HNSW scanning keeps going "
                    "until enough filtered rows are found, so a selective "
                    "predicate does not produce an empty result set."
                    if filters
                    else "No structured filters were parsed, so hybrid search "
                    "reduces to pure semantic search for this query."
                ),
            },
            "vector_info": vector_info(len(query_embedding)),
        }
    )
    return outcome
