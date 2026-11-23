"""Helpers for turning PostgreSQL EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
output into compact, UI-friendly technical details.
"""
from __future__ import annotations

from typing import Any


def _node_summary(node: dict, depth: int) -> dict:
    return {
        "depth": depth,
        "node_type": node.get("Node Type"),
        "relation": node.get("Relation Name"),
        "alias": node.get("Alias"),
        "index": node.get("Index Name"),
        "join_type": node.get("Join Type"),
        "actual_startup_ms": _round(node.get("Actual Startup Time")),
        "actual_total_ms": _round(node.get("Actual Total Time")),
        "actual_rows": node.get("Actual Rows"),
        "actual_loops": node.get("Actual Loops"),
        "plan_rows": node.get("Plan Rows"),
        "total_cost": _round(node.get("Total Cost")),
        "filter": node.get("Filter"),
        "index_condition": node.get("Index Cond"),
        "recheck_condition": node.get("Recheck Cond"),
        "rows_removed_by_filter": node.get("Rows Removed by Filter"),
        "sort_key": node.get("Sort Key"),
        "order_by": node.get("Order By"),
        "shared_hit_blocks": node.get("Shared Hit Blocks"),
        "shared_read_blocks": node.get("Shared Read Blocks"),
    }


def _round(value: Any, digits: int = 3) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


def _walk(node: dict, depth: int, nodes: list[dict], indexes: list[str]) -> None:
    nodes.append(_node_summary(node, depth))
    index = node.get("Index Name")
    if index and index not in indexes:
        indexes.append(index)
    for child in node.get("Plans", []) or []:
        _walk(child, depth + 1, nodes, indexes)


def parse_explain(explain_json: Any) -> dict:
    """Parse psycopg's JSON result from EXPLAIN (ANALYZE, BUFFERS)."""
    if isinstance(explain_json, str):
        import json

        explain_json = json.loads(explain_json)
    if isinstance(explain_json, list):
        root = explain_json[0]
    elif isinstance(explain_json, dict):
        root = explain_json
    else:
        return {"error": "Unexpected EXPLAIN output", "raw": str(explain_json)}

    plan = root.get("Plan", {})
    nodes: list[dict] = []
    indexes: list[str] = []
    _walk(plan, 0, nodes, indexes)

    node_types = [n["node_type"] for n in nodes if n.get("node_type")]
    seq_scans = node_types.count("Seq Scan")
    index_scans = sum(
        1 for t in node_types if t in {"Index Scan", "Index Only Scan", "Bitmap Index Scan"}
    )
    buffer = {
        "shared_hit_blocks": plan.get("Shared Hit Blocks"),
        "shared_read_blocks": plan.get("Shared Read Blocks"),
        "shared_dirtied_blocks": plan.get("Shared Dirtied Blocks"),
        "shared_written_blocks": plan.get("Shared Written Blocks"),
        "local_hit_blocks": plan.get("Local Hit Blocks"),
        "local_read_blocks": plan.get("Local Read Blocks"),
        "temp_read_blocks": plan.get("Temp Read Blocks"),
        "temp_written_blocks": plan.get("Temp Written Blocks"),
    }
    return {
        "execution_time_ms": _round(root.get("Execution Time")),
        "planning_time_ms": _round(root.get("Planning Time")),
        "top_node": plan.get("Node Type"),
        "indexes_used": indexes,
        "seq_scan_nodes": seq_scans,
        "index_scan_nodes": index_scans,
        "rows_returned_by_root": plan.get("Actual Rows"),
        "nodes": nodes,
        "buffers": buffer,
        "plan_json": explain_json,
    }
