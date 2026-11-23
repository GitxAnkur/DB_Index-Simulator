from __future__ import annotations

import pytest

from app import db

METHODS = ["full_scan", "btree", "hash", "composite_btree", "hnsw", "hybrid", "cached"]


def post_search(client, query, method, limit=5, include_plan=True):
    return client.post(
        "/api/search",
        json={"query": query, "method": method, "limit": limit, "include_plan": include_plan},
    )


@pytest.mark.parametrize("method", METHODS)
def test_all_seven_methods_return_results(client, method):
    response = post_search(client, "Black laptop under 80000", method, 5)
    assert response.status_code == 200
    data = response.get_json()
    assert data["method"] == method
    assert data["result_count"] == len(data["results"]) <= 5
    assert data["result_count"] > 0
    assert data["db_execution_ms"] >= 0
    assert data["execution_ms"] >= data["db_execution_ms"]
    assert data["technical"]["sql"]
    assert data["parsed_filters"]["category"] == "Laptop"
    assert data["parsed_filters"]["color"] == "Black"
    assert data["parsed_filters"]["max_price"] == 80000


@pytest.mark.parametrize("limit", [5, 10])
def test_result_limits(client, limit):
    for method in METHODS:
        response = post_search(client, "Laptop under 80000", method, limit)
        assert response.status_code == 200
        data = response.get_json()
        assert data["result_count"] <= limit
        assert len(data["results"]) <= limit


def test_relational_filters_are_applied(client):
    data = post_search(client, "Black laptop under 80000", "composite_btree", 10).get_json()
    assert data["results"]
    for product in data["results"]:
        assert product["category"] == "Laptop"
        assert product["color"] == "Black"
        assert float(product["price_inr"]) <= 80000


def test_full_scan_plan_has_no_index(client):
    data = post_search(client, "Black laptop under 80000", "full_scan", 5).get_json()
    plan = data["technical"]["explain"]
    assert plan["indexes_used"] == []
    assert plan["seq_scan_nodes"] >= 1


def test_btree_plan_uses_a_btree_index(client):
    data = post_search(client, "Black laptop under 80000", "btree", 5).get_json()
    indexes = data["technical"]["indexes_used"]
    assert indexes
    assert any("_btree" in name for name in indexes)


def test_hash_plan_uses_hash_index_for_brand(client):
    data = post_search(client, "Samsung smartphone", "hash", 5).get_json()
    indexes = data["technical"]["indexes_used"]
    assert "idx_products_brand_hash" in indexes
    assert data["technical"]["method_details"]["hash_index_applicable"] is True


def test_hash_reports_not_applicable_without_brand(client):
    data = post_search(client, "Laptop under 80000", "hash", 5).get_json()
    assert data["technical"]["method_details"]["hash_index_applicable"] is False
    assert any("hash index is not applicable" in w.lower() for w in data["warnings"])


def test_composite_plan_uses_composite_index(client):
    data = post_search(client, "Black laptop under 80000", "composite_btree", 5).get_json()
    assert "idx_products_category_price_color_btree" in data["technical"]["indexes_used"]
    assert data["technical"]["method_details"]["leading_column_present"] is True


def test_composite_reports_missing_leading_column(client):
    data = post_search(client, "Samsung smartphone", "composite_btree", 5).get_json()
    assert data["technical"]["method_details"]["leading_column_present"] is True
    data = post_search(client, "under 50000", "composite_btree", 5).get_json()
    assert data["technical"]["method_details"]["leading_column_present"] is False
    assert any("leading column" in w.lower() for w in data["warnings"])


def test_hnsw_uses_hnsw_index_and_similarity(client):
    data = post_search(client, "wireless headphones for travel", "hnsw", 5).get_json()
    assert "idx_products_embedding_hnsw" in data["technical"]["indexes_used"]
    assert data["technical"]["vector_info"]["metric"] == "cosine"
    assert data["technical"]["vector_info"]["dimension"] == 384
    for product in data["results"]:
        assert 0.0 <= float(product["similarity"]) <= 1.0


def test_hybrid_uses_semantic_ranking_and_structured_filter(client):
    data = post_search(client, "Black laptop under 80000", "hybrid", 5).get_json()
    assert data["technical"]["method_details"]["structured_filter_count"] >= 2
    assert data["technical"]["indexes_used"]
    assert all(p["category"] == "Laptop" for p in data["results"])
    assert all(float(p["price_inr"]) <= 80000 for p in data["results"])


def test_semantic_search_handles_terms_absent_from_dataset(client):
    # "wireless" is not a literal token in the dataset; embeddings still work.
    data = post_search(client, "wireless headphones for travel", "hnsw", 5).get_json()
    assert data["result_count"] == 5


def test_relational_keyword_fallback_is_reported(client):
    data = post_search(client, "Lightweight laptop for programming", "btree", 5).get_json()
    assert data["result_count"] == 5
    assert data["technical"]["fallback"] is not None
    assert any("relaxed" in w.lower() for w in data["warnings"])


def test_use_case_is_a_soft_ranking_preference(client):
    data = post_search(client, "Gaming monitor under 30000", "composite_btree", 5).get_json()
    assert data["result_count"] > 0
    assert data["parsed_filters"]["use_case"] == "gaming"
    assert data["technical"]["fallback"] is None


def test_cache_miss_then_hit(client):
    client.post("/api/cache/clear", json={})
    first = post_search(client, "Samsung smartphone", "cached", 5).get_json()
    second = post_search(client, "Samsung smartphone", "cached", 5).get_json()
    assert first["cache"]["status"] == "miss"
    assert second["cache"]["status"] == "hit"
    assert first["db_execution_ms"] > 0
    assert second["db_execution_ms"] == 0
    assert second["execution_ms"] < first["execution_ms"]
    assert [p["product_id"] for p in first["results"]] == [
        p["product_id"] for p in second["results"]
    ]


def test_cache_limit_is_part_of_key(client):
    client.post("/api/cache/clear", json={})
    first = post_search(client, "Laptop under 80000", "cached", 5).get_json()
    second = post_search(client, "Laptop under 80000", "cached", 10).get_json()
    assert first["cache"]["status"] == "miss"
    assert second["cache"]["status"] == "miss"


def test_invalid_method(client):
    response = post_search(client, "laptop", "nope", 5)
    assert response.status_code == 400
    assert "Unknown method" in response.get_json()["error"]


@pytest.mark.parametrize("limit", [0, 1, 7, 50, "5", True])
def test_invalid_limit(client, limit):
    response = client.post(
        "/api/search", json={"query": "laptop", "method": "btree", "limit": limit}
    )
    assert response.status_code == 400


def test_empty_query_rejected(client):
    response = client.post("/api/search", json={"query": "   ", "method": "btree", "limit": 5})
    assert response.status_code == 400


def test_non_json_body_rejected(client):
    response = client.post("/api/search", data="not json", content_type="text/plain")
    assert response.status_code == 400


def test_sql_injection_is_parameterised(client, product_count):
    payload = "laptop' OR 1=1; DROP TABLE products; --"
    response = post_search(client, payload, "btree", 5)
    assert response.status_code == 200
    data = response.get_json()
    assert "DROP TABLE" not in data["technical"]["sql"]
    assert db.fetch_one("SELECT count(*) AS n FROM products")["n"] == product_count == 100_000


def test_sql_does_not_embed_user_input(client):
    data = post_search(client, "Samsung smartphone", "btree", 5).get_json()
    sql = data["technical"]["sql"]
    assert "Samsung" not in sql
    assert "Smartphone" not in sql
    assert "Samsung" in data["technical"]["params"]


def test_product_detail_endpoint(client):
    response = client.get("/api/products/P000001")
    assert response.status_code == 200
    assert response.get_json()["product_id"] == "P000001"
    assert client.get("/api/products/DOESNOTEXIST").status_code == 404
