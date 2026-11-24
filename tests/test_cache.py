from __future__ import annotations

import time

from app.cache import TTLCache, cache


def test_cache_hit_miss_and_stats(client):
    client.post("/api/cache/clear", json={})
    first = client.post(
        "/api/search", json={"query": "Samsung smartphone", "method": "cached", "limit": 5}
    ).get_json()
    second = client.post(
        "/api/search", json={"query": "Samsung smartphone", "method": "cached", "limit": 5}
    ).get_json()
    assert first["cache"]["status"] == "miss"
    assert second["cache"]["status"] == "hit"
    assert second["cache"]["key"] == first["cache"]["key"]
    assert second["db_execution_ms"] == 0
    stats = client.get("/api/cache/stats").get_json()
    assert stats["entries"] >= 1
    assert stats["hits"] >= 1
    assert stats["misses"] >= 1


def test_cache_clear_endpoint(client):
    client.post(
        "/api/search", json={"query": "Laptop under 80000", "method": "cached", "limit": 5}
    )
    response = client.post("/api/cache/clear", json={})
    assert response.status_code == 200
    data = response.get_json()
    assert data["cleared_entries"] >= 1
    assert data["stats"]["entries"] == 0
    # Next identical query is a miss again.
    again = client.post(
        "/api/search", json={"query": "Laptop under 80000", "method": "cached", "limit": 5}
    ).get_json()
    assert again["cache"]["status"] == "miss"


def test_cache_key_includes_query_and_limit(client):
    client.post("/api/cache/clear", json={})
    a = client.post(
        "/api/search", json={"query": "Laptop under 80000", "method": "cached", "limit": 5}
    ).get_json()
    b = client.post(
        "/api/search", json={"query": "Laptop under 80000", "method": "cached", "limit": 10}
    ).get_json()
    c = client.post(
        "/api/search", json={"query": "Laptop under 90000", "method": "cached", "limit": 5}
    ).get_json()
    assert a["cache"]["key"] != b["cache"]["key"]
    assert a["cache"]["key"] != c["cache"]["key"]


def test_cache_is_not_used_by_other_methods(client):
    client.post("/api/cache/clear", json={})
    data = client.post(
        "/api/search", json={"query": "Laptop under 80000", "method": "composite_btree", "limit": 5}
    ).get_json()
    assert data["cache"] is None


def test_ttl_cache_expiry():
    local = TTLCache(max_entries=2, ttl_seconds=0.05)
    local.set("a", {"value": 1})
    value, meta = local.get("a")
    assert value == {"value": 1}
    assert meta["status"] == "hit"
    time.sleep(0.08)
    value, meta = local.get("a")
    assert value is None
    assert meta["status"] == "miss"
    assert meta["reason"] == "expired"
    assert local.stats()["expirations"] == 1


def test_ttl_cache_lru_eviction():
    local = TTLCache(max_entries=2, ttl_seconds=60)
    local.set("a", 1)
    local.set("b", 2)
    local.get("a")
    local.set("c", 3)
    assert local.get("b")[0] is None
    assert local.get("a")[0] == 1
    assert local.get("c")[0] == 3
    assert local.stats()["evictions"] == 1


def test_global_cache_configured_from_app():
    assert cache.max_entries >= 1
    assert cache.ttl_seconds >= 1
