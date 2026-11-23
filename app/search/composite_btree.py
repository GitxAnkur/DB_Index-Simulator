"""Method 4: composite (multicolumn) B-tree search.

The index is (category, price_inr, color). Category is the leading column, so
the index is only usable when the query constrains category. Column order and
the leading-column rule are demonstrated in the query plan and documentation.
"""
from __future__ import annotations

from ..query_parser import ParsedQuery
from .base import execute_relational

METHOD = "composite_btree"
LABEL = "Composite B+ Tree Search"
DESCRIPTION = (
    "A multicolumn B-tree on (category, price_inr, color). The leading-column "
    "rule means category is required for the index to be applicable."
)
EXPECTED_INDEX = "idx_products_category_price_color_btree"


def search(parsed: ParsedQuery, limit: int, include_plan: bool = True) -> dict:
    outcome = execute_relational(parsed, limit, include_plan)
    applicable = bool(parsed.category)
    outcome.update(
        {
            "planner_settings": [],
            "method_details": {
                "index_family": "composite B-tree",
                "index": "idx_products_category_price_color_btree",
                "columns": ["category", "price_inr", "color"],
                "leading_column_present": applicable,
                "leading_column": "category",
                "price_predicate": parsed.min_price is not None or parsed.max_price is not None,
                "color_predicate": bool(parsed.color),
                "note": (
                    "The composite index can be used when category is constrained. "
                    "Price and colour are additional columns; colour is after the "
                    "range column, so a colour-only restriction after a price range "
                    "may not be as selective as the leading columns. "
                    + (
                        "Category predicate is present."
                        if applicable
                        else "No category predicate is present, so the leading "
                        "column rule makes this index inapplicable."
                    )
                ),
                "fallback_used": bool(outcome.get("fallback")),
            },
            "vector_info": None,
        }
    )
    return outcome
