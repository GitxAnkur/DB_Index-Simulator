"""Method 3: PostgreSQL hash index search.

A hash index supports equality predicates only; it cannot serve range queries
or ordering. The hash index is on brand. If the natural-language query has no
brand, the method reports that the hash index is not applicable and falls back
to the ordinary structured query rather than pretending the index was used.
"""
from __future__ import annotations

from ..query_parser import ParsedQuery
from .base import execute_relational

METHOD = "hash"
LABEL = "Hash Index Search"
DESCRIPTION = (
    "A PostgreSQL hash index on brand accelerates equality lookups. Hash "
    "indexes do not support ranges or sorting; queries without a brand cannot "
    "use this index."
)
EXPECTED_INDEX = "idx_products_brand_hash"


def search(parsed: ParsedQuery, limit: int, include_plan: bool = True) -> dict:
    outcome = execute_relational(parsed, limit, include_plan)
    applicable = bool(parsed.brand)
    outcome.update(
        {
            "planner_settings": [],
            "method_details": {
                "index_family": "hash",
                "index": "idx_products_brand_hash (brand)",
                "equality_predicate_present": applicable,
                "hash_index_applicable": applicable,
                "note": (
                    "Hash indexes support equality only. No range or ORDER BY "
                    "support is claimed. "
                    + (
                        f"Brand equality predicate: {parsed.brand}."
                        if applicable
                        else "The query contains no brand, so the hash index is "
                        "not applicable and the plan may show a sequential scan."
                    )
                ),
                "fallback_used": bool(outcome.get("fallback")),
            },
            "vector_info": None,
        }
    )
    return outcome
