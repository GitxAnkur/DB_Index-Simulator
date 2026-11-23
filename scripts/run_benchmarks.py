#!/usr/bin/env python3
"""Run the fixed benchmark query suite and write real results to CSV/JSON.

Usage:
    .venv/bin/python scripts/run_benchmarks.py --repetitions 5 --limit 10
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.benchmark import FIXED_SUITE, benchmark_to_csv, run_benchmark  # noqa: E402
from app.config import Config  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--methods", nargs="*", default=None)
    parser.add_argument("--csv", type=Path, default=Config.DOCS_DIR / "benchmark_results.csv")
    parser.add_argument("--json", type=Path, default=ROOT / "data" / "benchmark_results.json")
    parser.add_argument("--summary", type=Path, default=Config.DOCS_DIR / "benchmark_summary.md")
    args = parser.parse_args()

    results = []
    csv_parts = []
    header_written = False
    for index, query in enumerate(FIXED_SUITE, start=1):
        print(f"[{index}/{len(FIXED_SUITE)}] {query}", flush=True)
        result = run_benchmark(
            query,
            methods=args.methods,
            limit=args.limit,
            repetitions=args.repetitions,
            clear_cache=True,
            warmup_runs=1,
            capture_representative_plan=True,
        )
        results.append(result)
        csv_text = benchmark_to_csv(result)
        rows = list(csv.reader(io.StringIO(csv_text)))
        if not header_written:
            csv_parts.extend(rows)
            header_written = True
        else:
            csv_parts.extend(rows[1:])
        for row in result["comparison_table"]:
            print(
                f"    {row['method']:<16} median={row['median_ms']} ms "
                f"min={row['min_ms']} max={row['max_ms']} "
                f"success={row['successful_runs']}"
            )

    args.csv.parent.mkdir(parents=True, exist_ok=True)
    args.json.parent.mkdir(parents=True, exist_ok=True)
    with args.csv.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerows(csv_parts)

    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "repetitions": args.repetitions,
        "limit": args.limit,
        "queries": FIXED_SUITE,
        "results": results,
    }
    args.json.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    lines = [
        "# Fixed-Suite Benchmark Summary",
        "",
        f"Generated: {payload['generated_at_utc']}  ",
        f"Repetitions per method: {args.repetitions}  ",
        f"Result limit: {args.limit}  ",
        "Statistic: median database execution time in milliseconds.",
        "",
        "| Query | " + " | ".join(
            ["Full scan", "B-tree", "Hash", "Composite", "HNSW", "Hybrid", "Cached"]
        ) + " |",
        "|---|" + "---:|" * 7,
    ]
    for result in results:
        medians = {row["method"]: row["median_ms"] for row in result["comparison_table"]}
        lines.append(
            f"| {result['query']} | "
            + " | ".join(
                str(medians.get(m, "—"))
                for m in [
                    "full_scan", "btree", "hash", "composite_btree",
                    "hnsw", "hybrid", "cached",
                ]
            )
            + " |"
        )
    lines += [
        "",
        "The cached method starts with a cache miss and then reports hits; its "
        "median is often 0 ms because most repetitions bypass the database.",
        "HNSW and hybrid timings are database execution only; query embedding "
        "time is reported separately in the JSON/CSV.",
        "",
    ]
    args.summary.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nWrote {args.csv}, {args.json}, {args.summary}")


if __name__ == "__main__":
    main()
