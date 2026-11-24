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
LABEL = "B+ Tree"
DESCRIPTION = (
    "PostgreSQL B-tree indexes on price_inr, category and rating support "
    "equality and range predicates. The actual chosen index is shown in the "
    "query plan."
)
EXPECTED_INDEX = (
    "idx_products_price_btree / idx_products_category_btree / "
    "idx_products_rating_btree"
)


def search(parsed: ParsedQuery, limit: int, include_plan: bool = True) -> dict:
    outcome = execute_relational(parsed, limit, include_plan)
    outcome.update(
        {
            "planner_settings": [],
            "method_details": {
                "index_family": "B-tree",
                "indexes_available": [
                    "idx_products_price_btree",
                    "idx_products_category_btree",
                    "idx_products_rating_btree",
                ],
                "note": (
                    "PostgreSQL chooses among the available B-tree indexes. "
                    "The actual index used for this query is reported by the "
                    "query plan; the method does not force a particular index."
                ),
                "fallback_used": False,
            },
            "vector_info": None,
        }
    )
    return outcome
