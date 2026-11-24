"""Method 5: HNSW approximate nearest-neighbour vector search."""
from __future__ import annotations

import numpy as np

from ..config import Config
from ..embeddings import to_pgvector
from ..query_parser import ParsedQuery
from .base import (
    PRODUCT_COLUMNS,
    execute_sql,
    similarity_expression,
    vector_info,
    vector_settings,
)

METHOD = "hnsw"
LABEL = "HNSW Vector Search"
DESCRIPTION = (
    "Cosine-distance semantic search over 384-dimensional product embeddings "
    "using a pgvector HNSW index. No structured filters are applied."
)
EXPECTED_INDEX = "idx_products_embedding_hnsw"


def search(
    parsed: ParsedQuery,
    limit: int,
    include_plan: bool = True,
    query_embedding: np.ndarray | None = None,
) -> dict:
    if query_embedding is None:
        raise ValueError("HNSW search requires a query embedding")
    vector = to_pgvector(query_embedding)
    sql = (
        f"SELECT {PRODUCT_COLUMNS}, {similarity_expression()} "
        "FROM products WHERE embedding IS NOT NULL "
        "ORDER BY embedding <=> %s::vector LIMIT %s"
    )
    outcome = execute_sql(
        sql, [vector, vector, limit], vector_settings(), include_plan
    )

    # Second safety net: discard weak nearest neighbours. The scope gate has
    # already rejected unrelated prompts, but a borderline query can still
    # produce low-similarity rows. Keeping only genuine matches means an
    # out-of-scope search can return zero products instead of noise.
    threshold = Config.HNSW_MIN_SIMILARITY
    scored_rows = outcome.get("rows", [])
    kept_rows = [
        row for row in scored_rows
        if float(row.get("similarity") or 0.0) >= threshold
    ]
    outcome["rows"] = kept_rows

    outcome.update(
        {
            "sql": sql,
            "params": [f"<{len(query_embedding)}-dim query vector>", f"<{len(query_embedding)}-dim query vector>", limit],
            "planner_settings": [f"hnsw.ef_search = {vector_info()['ef_search']}"],
            "method_details": {
                "search_type": "approximate nearest neighbour (HNSW)",
                "structured_filters": False,
                "semantic_query": parsed.original_query,
                "min_similarity": threshold,
                "rows_before_similarity_filter": len(scored_rows),
                "rows_after_similarity_filter": len(kept_rows),
                "note": (
                    "The query is embedded with the same Sentence Transformers "
                    "model used for product documents. Results are ordered by "
                    "cosine distance and rows below the minimum similarity are "
                    "discarded. HNSW is approximate, so recall depends on "
                    "ef_search and index parameters."
                ),
            },
            "vector_info": vector_info(len(query_embedding)),
        }
    )
    return outcome
