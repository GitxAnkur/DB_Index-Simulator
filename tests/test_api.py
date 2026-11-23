from __future__ import annotations

from app import db


def test_unknown_api_endpoint_returns_json_404(client):
    response = client.get("/api/does-not-exist")
    assert response.status_code == 404
    assert response.is_json
    assert response.get_json()["error"] == "Endpoint not found"


def test_method_not_allowed_returns_json_405(client):
    response = client.get("/api/search")
    assert response.status_code == 405
    assert response.is_json


def test_root_page_serves_frontend(client):
    response = client.get("/")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Indexed Product Search" in body
    assert "Benchmark dashboard" in body
    assert "chart.umd.min.js" in body


def test_database_connection_and_extension():
    row = db.fetch_one("SELECT version() AS version")
    assert "PostgreSQL" in row["version"]
    vector = db.fetch_one(
        "SELECT extversion AS v FROM pg_extension WHERE extname='vector'"
    )
    assert vector["v"].startswith("0.8")


def test_category_distribution_matches_validation():
    rows = db.fetch_all(
        "SELECT category, count(*) AS n FROM products GROUP BY category ORDER BY category"
    )
    assert len(rows) == 10
    assert sum(r["n"] for r in rows) == 100_000
