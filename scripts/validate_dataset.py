#!/usr/bin/env python3
"""Validate the fixed 100,000-row synthetic product dataset.

The original CSV is never modified. A machine-readable JSON report and a
human-readable Markdown report are written to data/ and docs/.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CSV = ROOT / "synthetic_products_100000.csv"
EXPECTED_CATEGORIES = {
    "Laptop": 10_000,
    "Smartphone": 10_000,
    "Headphones": 10_000,
    "Tablet": 10_000,
    "Smartwatch": 10_000,
    "Monitor": 10_000,
    "Keyboard": 10_000,
    "Gaming Accessories": 10_000,
    "Camera": 10_000,
    "Speaker": 10_000,
}
REQUIRED_COLUMNS = [
    "product_id",
    "name",
    "category",
    "brand",
    "price_inr",
    "color",
    "rating",
    "stock_quantity",
    "use_case",
    "specifications",
    "description",
    "tags",
    "image_key",
    "image_prompt",
]


def validate(csv_path: Path) -> dict:
    if not csv_path.exists():
        raise FileNotFoundError(f"Dataset not found: {csv_path}")

    # utf-8-sig strips the UTF-8 BOM that is present in the supplied CSV.
    df = pd.read_csv(csv_path, encoding="utf-8-sig")

    missing_columns = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    extra_columns = [c for c in df.columns if c not in REQUIRED_COLUMNS]

    ids = df["product_id"].astype(str)
    price = pd.to_numeric(df["price_inr"], errors="coerce")
    rating = pd.to_numeric(df["rating"], errors="coerce")
    stock = pd.to_numeric(df["stock_quantity"], errors="coerce")

    category_counts = df["category"].value_counts().to_dict()
    category_counts = {str(k): int(v) for k, v in sorted(category_counts.items())}

    checks = {
        "row_count_exact": bool(len(df) == 100_000),
        "unique_product_ids": bool(ids.nunique() == len(df)),
        "ten_categories": bool(len(category_counts) == 10),
        "category_distribution": bool(
            category_counts == dict(sorted(EXPECTED_CATEGORIES.items()))
        ),
        "no_missing_values": bool(int(df.isna().sum().sum()) == 0),
        "prices_numeric_nonnegative": bool(
            price.notna().all() and (price >= 0).all()
        ),
        "ratings_in_range": bool(
            rating.notna().all() and ((rating >= 0) & (rating <= 5)).all()
        ),
        "stock_nonnegative": bool(
            stock.notna().all() and (stock >= 0).all()
        ),
        "no_duplicate_records": bool(int(df.duplicated().sum()) == 0),
        "product_id_format": bool(ids.str.fullmatch(r"P\d{6}").all()),
        "id_range_complete": bool(
            ids.min() == "P000001" and ids.max() == "P100000"
        ),
    }

    report = {
        "dataset": str(csv_path.name),
        "validated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sha256_note": "The original CSV is read-only during validation and import.",
        "rows": int(len(df)),
        "columns": list(df.columns),
        "missing_columns": missing_columns,
        "extra_columns": extra_columns,
        "unique_product_ids": int(ids.nunique()),
        "duplicate_product_ids": int(len(df) - ids.nunique()),
        "duplicate_records": int(df.duplicated().sum()),
        "duplicate_names": int(df["name"].duplicated().sum()),
        "missing_values_total": int(df.isna().sum().sum()),
        "missing_values_by_column": {
            str(k): int(v) for k, v in df.isna().sum().items()
        },
        "categories": category_counts,
        "brands": int(df["brand"].nunique()),
        "colors": sorted(str(x) for x in df["color"].dropna().unique()),
        "use_cases": int(df["use_case"].nunique()),
        "price_inr": {
            "min": float(price.min()),
            "max": float(price.max()),
            "mean": round(float(price.mean()), 2),
            "invalid_or_negative": int((price.isna() | (price < 0)).sum()),
        },
        "rating": {
            "min": float(rating.min()),
            "max": float(rating.max()),
            "mean": round(float(rating.mean()), 3),
            "out_of_range": int(
                (rating.isna() | (rating < 0) | (rating > 5)).sum()
            ),
        },
        "stock_quantity": {
            "min": int(stock.min()),
            "max": int(stock.max()),
            "negative": int((stock < 0).sum()),
        },
        "checks": checks,
        "all_checks_passed": all(checks.values()),
        "notes": [
            "The supplied category labels are singular (for example 'Laptop'). "
            "They are preserved exactly in PostgreSQL; the UI displays the "
            "same labels.",
            "Product names are intentionally non-unique; the primary key is "
            "product_id and no duplicate rows exist.",
            "The CSV has a UTF-8 BOM in its header; imports use utf-8-sig.",
            "image_key and image_prompt are preserved for a future image system; "
            "no images are generated in this version.",
        ],
    }
    return report


def write_markdown(report: dict, path: Path) -> None:
    checks = report["checks"]
    lines = [
        "# Dataset Validation Report",
        "",
        f"**Dataset:** `{report['dataset']}`  ",
        f"**Validated:** {report['validated_at_utc']}  ",
        f"**Rows:** {report['rows']:,}  ",
        f"**Overall status:** {'PASS' if report['all_checks_passed'] else 'FAIL'}",
        "",
        "The original CSV was not modified. It was read with UTF-8 BOM "
        "handling and validated before import.",
        "",
        "## Checks",
        "",
        "| Check | Result |",
        "|---|---|",
    ]
    for name, value in checks.items():
        lines.append(f"| `{name}` | {'PASS' if value else 'FAIL'} |")

    lines += [
        "",
        "## Category distribution",
        "",
        "| Category | Products | Expected |",
        "|---|---:|---:|",
    ]
    for cat, count in report["categories"].items():
        lines.append(f"| {cat} | {count:,} | 10,000 |")

    p = report["price_inr"]
    r = report["rating"]
    s = report["stock_quantity"]
    lines += [
        "",
        "## Data quality",
        "",
        f"- Unique product IDs: **{report['unique_product_ids']:,}**",
        f"- Duplicate product IDs: **{report['duplicate_product_ids']}**",
        f"- Duplicate full records: **{report['duplicate_records']}**",
        f"- Missing values: **{report['missing_values_total']}**",
        f"- Distinct brands: **{report['brands']}**",
        f"- Distinct use cases: **{report['use_cases']}**",
        f"- Colours: {', '.join(report['colors'])}",
        f"- Price (INR): min **{p['min']:,.2f}**, max **{p['max']:,.2f}**, "
        f"mean **{p['mean']:,.2f}**, invalid/negative **{p['invalid_or_negative']}**",
        f"- Rating: min **{r['min']}**, max **{r['max']}**, mean **{r['mean']}**, "
        f"out of range **{r['out_of_range']}**",
        f"- Stock: min **{s['min']}**, max **{s['max']}**, negative **{s['negative']}**",
        "",
        "## Notes",
        "",
    ]
    for note in report["notes"]:
        lines.append(f"- {note}")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--json", type=Path, default=ROOT / "data" / "dataset_validation.json")
    parser.add_argument("--markdown", type=Path, default=ROOT / "docs" / "validation_report.md")
    args = parser.parse_args()

    report = validate(args.csv)
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(report, indent=2), encoding="utf-8")
    write_markdown(report, args.markdown)

    print(json.dumps({
        "rows": report["rows"],
        "categories": report["categories"],
        "all_checks_passed": report["all_checks_passed"],
        "json": str(args.json),
        "markdown": str(args.markdown),
    }, indent=2))
    if not report["all_checks_passed"]:
        failed = [k for k, v in report["checks"].items() if not v]
        raise SystemExit(f"Dataset validation failed: {failed}")


if __name__ == "__main__":
    main()
