"""Method 3: composite (multicolumn) index search.

The index is (category, price_inr, color). Category is the leading column, so
the index is only usable when the query constrains category. Results are
ordered by price and colour, which lets the same index satisfy the filter and
the ordering instead of falling back to a smaller single-column index.
"""
from __future__ import annotations

from ..query_parser import ParsedQuery
from .base import PRODUCT_COLUMNS, execute_sql, structured_conditions

METHOD = "composite_btree"
LABEL = "Composite Index"
DESCRIPTION = (
    "A multicolumn index on (category, price_inr, color). The leading-column "
    "rule means category is required. Results are ordered by price and colour "
    "so the index serves both the filter and the ordering."
)
EXPECTED_INDEX = "idx_products_category_price_color_btree"

# Matches the trailing columns of the composite index, so PostgreSQL can use
# the index for filtering and ordering in one pass.
COMPOSITE_ORDER = "price_inr ASC NULLS LAST, color ASC NULLS LAST, product_id ASC"


def search(parsed: ParsedQuery, limit: int, include_plan: bool = True) -> dict:
    where_sql, params = structured_conditions(parsed, include_keywords=True)
    sql = (
        f"SELECT {PRODUCT_COLUMNS} FROM products WHERE {where_sql} "
        f"ORDER BY {COMPOSITE_ORDER} LIMIT %s"
    )
    outcome = execute_sql(sql, [*params, limit], (), include_plan)
    applicable = bool(parsed.category)
    outcome.update(
        {
            "sql": sql,
            "params": [*params, limit],
            "fallback": None,
            "planner_settings": [],
            "method_details": {
                "index_family": "composite",
                "index": "idx_products_category_price_color_btree",
                "columns": ["category", "price_inr", "color"],
                "order_by": COMPOSITE_ORDER,
                "leading_column_present": applicable,
                "leading_column": "category",
                "price_predicate": parsed.min_price is not None or parsed.max_price is not None,
                "color_predicate": bool(parsed.color),
                "note": (
                    "The composite index can be used when category is constrained. "
                    "Price and colour are additional columns; the result order "
                    "follows the index so the planner can scan it directly. "
                    + (
                        "Category predicate is present."
                        if applicable
                        else "No category predicate is present, so the leading "
                        "column rule makes this index inapplicable."
                    )
                ),
                "fallback_used": False,
            },
            "vector_info": None,
        }
    )
    return outcome
