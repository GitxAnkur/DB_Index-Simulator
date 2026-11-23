"""Method 2: PostgreSQL B-tree search.

PostgreSQL implements B-tree indexes, which serve the B+ tree concept being
demonstrated. Single-column B-tree indexes exist on price_inr, category and
rating. The planner may also select the multicolumn B-tree index; the actual
index used is always reported from EXPLAIN ANALYZE.
"""
from __future__ import annotations

from ..query_parser import ParsedQuery
from .base import execute_relational

METHOD = "btree"
LABEL = "B+ Tree Search"
DESCRIPTION = (
    "PostgreSQL B-tree indexes on price_inr, category and rating support "
    "equality and range predicates. The actual chosen index is shown in the "
    "query plan."
)
EXPECTED_INDEX = "idx_products_price_btree / idx_products_category_btree / idx_products_rating_btree"


def search(parsed: ParsedQuery, limit: int, include_plan: bool = True) -> dict:
    outcome = execute_relational(parsed, limit, include_plan)
    outcome.update(
        {
            "planner_settings": [],
            "method_details": {
                "index_family": "B-tree",
                "single_column_indexes": [
                    "idx_products_price_btree (price_inr)",
                    "idx_products_category_btree (category)",
                    "idx_products_rating_btree (rating)",
                ],
                "note": (
                    "The planner decides whether an index is selective enough. "
                    "If EXPLAIN shows a Seq Scan, that is reported honestly rather "
                    "than claiming index usage."
                ),
                "fallback_used": bool(outcome.get("fallback")),
            },
            "vector_info": None,
        }
    )
    return outcome
