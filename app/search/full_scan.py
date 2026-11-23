"""Method 1: baseline full-table scan.

Index scans and bitmap scans are disabled for this method so the baseline is a
true sequential scan. This is a deliberate experimental control, reported in
the technical details. The planner may still choose a sequential scan for
index-based methods when a filter is not selective.
"""
from __future__ import annotations

from ..query_parser import ParsedQuery
from .base import execute_relational

METHOD = "full_scan"
LABEL = "Normal Search / Full Table Scan"
DESCRIPTION = (
    "Sequential scan baseline. Index scans and bitmap scans are disabled for "
    "this measurement, so PostgreSQL must read the table sequentially."
)
EXPECTED_INDEX = None


def search(parsed: ParsedQuery, limit: int, include_plan: bool = True) -> dict:
    settings = [
        "SET LOCAL enable_indexscan = off",
        "SET LOCAL enable_indexonlyscan = off",
        "SET LOCAL enable_bitmapscan = off",
        "SET LOCAL enable_seqscan = on",
    ]
    outcome = execute_relational(parsed, limit, include_plan, settings)
    outcome.update(
        {
            "planner_settings": [
                "enable_indexscan = off",
                "enable_indexonlyscan = off",
                "enable_bitmapscan = off",
            ],
            "method_details": {
                "scan_type": "sequential scan (forced baseline)",
                "index_scans_disabled": True,
                "note": (
                    "The full table is scanned. Keyword predicates and structured "
                    "filters are applied row by row. This baseline is not assumed "
                    "to be the slowest method for every query."
                ),
                "fallback_used": bool(outcome.get("fallback")),
            },
            "vector_info": None,
        }
    )
    return outcome
