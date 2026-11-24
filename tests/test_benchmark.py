from __future__ import annotations

import csv
import io
import statistics

from app.benchmark import FIXED_SUITE


def test_health_reports_database_and_dataset(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.get_json()
    assert data["healthy"] is True
    assert data["database"]["product_count"] == 100_000
    assert data["database"]["embedded_count"] == 100_000
    assert data["database"]["pgvector_version"] == "0.8.7"
    assert len(data["methods"]) == 6
    assert data["dataset_validation"]["all_checks_passed"] is True
    assert any(i["indexname"] == "idx_products_embedding_hnsw" for i in data["database"]["indexes"])


def test_methods_endpoint_lists_exactly_six(client):
    data = client.get("/api/methods").get_json()
    ids = [m["id"] for m in data["methods"]]
    assert ids == [
        "full_scan", "hash", "composite_btree", "hnsw", "hybrid", "cached",
    ]


def test_benchmark_suite_endpoint(client):
    data = client.get("/api/benchmark/suite").get_json()
    assert data["queries"] == FIXED_SUITE
    assert len(data["queries"]) == 7
    assert data["repetitions_min"] == 5


def test_benchmark_repetitions_and_statistics(client):
    payload = {
        "query": "Laptop under 80000",
        "methods": ["full_scan", "hash", "composite_btree", "hnsw", "hybrid", "cached"],
        "limit": 5,
        "repetitions": 5,
        "clear_cache": True,
        "warmup_runs": 1,
    }
    response = client.post("/api/benchmark", json=payload)
    assert response.status_code == 200
    data = response.get_json()
    assert len(data["methods"]) == 6
    assert len(data["comparison_table"]) == 6
    for method in data["methods"]:
        assert method["repetitions"] == 5
        assert len(method["samples"]) == 5
        assert method["successful_runs"] == 5
        assert method["failed_runs"] == 0
        values = [s["db_execution_ms"] for s in method["samples"]]
        assert method["stats"]["median_ms"] == round(statistics.median(values), 3)
        assert method["stats"]["min_ms"] == round(min(values), 3)
        assert method["stats"]["max_ms"] == round(max(values), 3)
        assert method["stats"]["mean_ms"] == round(statistics.fmean(values), 3)
        assert method["representative_plan"] is not None
    cached = next(m for m in data["methods"] if m["method"] == "cached")
    assert cached["cache_conditions"]["miss_runs"] == 1
    assert cached["cache_conditions"]["hit_runs"] == 4
    assert cached["cache_conditions"]["statuses"] == ["miss", "hit", "hit", "hit", "hit"]
    assert data["conditions"]["same_result_limit"] == 5
    assert data["conditions"]["application_cache"]["cleared_before_cached_method"] is True


def test_benchmark_rejects_too_few_repetitions(client):
    response = client.post(
        "/api/benchmark",
        json={"query": "laptop", "methods": ["composite_btree"], "limit": 5, "repetitions": 4},
    )
    assert response.status_code == 400
    assert "Repetitions" in response.get_json()["error"]


def test_benchmark_rejects_too_many_repetitions(client):
    response = client.post(
        "/api/benchmark",
        json={"query": "laptop", "methods": ["composite_btree"], "limit": 5, "repetitions": 21},
    )
    assert response.status_code == 400


def test_benchmark_rejects_unknown_method(client):
    response = client.post(
        "/api/benchmark",
        json={"query": "laptop", "methods": ["nope"], "limit": 5, "repetitions": 5},
    )
    assert response.status_code == 400


def test_benchmark_rejects_empty_method_list(client):
    response = client.post(
        "/api/benchmark",
        json={"query": "laptop", "methods": [], "limit": 5, "repetitions": 5},
    )
    assert response.status_code == 400


def test_benchmark_csv_export(client):
    payload = {
        "query": "Laptop under 80000",
        "methods": ["full_scan", "composite_btree"],
        "limit": 5,
        "repetitions": 5,
        "clear_cache": True,
        "capture_representative_plan": False,
    }
    response = client.post("/api/benchmark/export", json=payload)
    assert response.status_code == 200
    assert response.mimetype == "text/csv"
    assert "attachment" in response.headers["Content-Disposition"]
    rows = list(csv.DictReader(io.StringIO(response.get_data(as_text=True))))
    assert len(rows) == 10
    assert {row["method"] for row in rows} == {"full_scan", "composite_btree"}
    assert all(row["db_execution_ms"] for row in rows)
    assert all(row["median_ms"] for row in rows)


def test_benchmark_export_rejects_bad_query(client):
    response = client.post("/api/benchmark/export", json={"query": ""})
    assert response.status_code == 400
