from __future__ import annotations

import json

from app import db
from app.config import Config


def test_exactly_100000_products():
    assert db.fetch_one("SELECT count(*) AS n FROM products")["n"] == 100_000


def test_unique_product_ids_and_range():
    row = db.fetch_one(
        "SELECT count(*) AS n, count(DISTINCT product_id) AS unique_ids, "
        "min(product_id) AS first, max(product_id) AS last FROM products"
    )
    assert row["n"] == row["unique_ids"] == 100_000
    assert row["first"] == "P000001"
    assert row["last"] == "P100000"


def test_ten_categories_10000_each():
    rows = db.fetch_all(
        "SELECT category, count(*) AS n FROM products GROUP BY category ORDER BY category"
    )
    assert len(rows) == 10
    assert all(row["n"] == 10_000 for row in rows)
    assert {row["category"] for row in rows} == {
        "Laptop", "Smartphone", "Headphones", "Tablet", "Smartwatch",
        "Monitor", "Keyboard", "Gaming Accessories", "Camera", "Speaker",
    }


def test_no_missing_values():
    row = db.fetch_one(
        "SELECT count(*) AS n FROM products WHERE "
        "product_id IS NULL OR name IS NULL OR category IS NULL OR brand IS NULL "
        "OR price_inr IS NULL OR color IS NULL OR rating IS NULL "
        "OR stock_quantity IS NULL OR use_case IS NULL OR specifications IS NULL "
        "OR description IS NULL OR tags IS NULL OR image_key IS NULL "
        "OR image_prompt IS NULL"
    )
    assert row["n"] == 0


def test_constraints_and_value_ranges():
    row = db.fetch_one(
        "SELECT count(*) FILTER (WHERE price_inr < 0) AS negative_prices, "
        "count(*) FILTER (WHERE rating < 0 OR rating > 5) AS bad_ratings, "
        "count(*) FILTER (WHERE stock_quantity < 0) AS negative_stock, "
        "min(price_inr) AS min_price, max(price_inr) AS max_price, "
        "min(rating) AS min_rating, max(rating) AS max_rating "
        "FROM products"
    )
    assert row["negative_prices"] == 0
    assert row["bad_ratings"] == 0
    assert row["negative_stock"] == 0
    assert row["min_price"] >= 0
    assert row["max_price"] > 0
    assert 0 <= row["min_rating"] <= row["max_rating"] <= 5


def test_all_embeddings_present_with_correct_dimension():
    row = db.fetch_one(
        "SELECT count(*) AS total, count(embedding) AS embedded, "
        "min(vector_dims(embedding)) AS min_dim, max(vector_dims(embedding)) AS max_dim "
        "FROM products"
    )
    assert row["total"] == 100_000
    assert row["embedded"] == 100_000
    assert row["min_dim"] == row["max_dim"] == Config.EMBEDDING_DIM


def test_required_indexes_exist():
    rows = db.fetch_all(
        "SELECT indexname, indexdef FROM pg_indexes WHERE tablename='products'"
    )
    names = {row["indexname"] for row in rows}
    assert "idx_products_price_btree" in names
    assert "idx_products_category_btree" in names
    assert "idx_products_rating_btree" in names
    assert "idx_products_brand_hash" in names
    assert "idx_products_category_price_color_btree" in names
    assert "idx_products_embedding_hnsw" in names
    definitions = {row["indexname"]: row["indexdef"] for row in rows}
    assert "USING hash" in definitions["idx_products_brand_hash"]
    assert "USING hnsw" in definitions["idx_products_embedding_hnsw"]
    assert "vector_cosine_ops" in definitions["idx_products_embedding_hnsw"]


def test_dataset_validation_report_passed():
    assert Config.VALIDATION_JSON.exists()
    report = json.loads(Config.VALIDATION_JSON.read_text(encoding="utf-8"))
    assert report["rows"] == 100_000
    assert report["all_checks_passed"] is True
    assert all(report["checks"].values())
    assert len(report["categories"]) == 10
