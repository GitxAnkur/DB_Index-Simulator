"""Shared pytest fixtures. Tests use the real PostgreSQL database."""
from __future__ import annotations

import pytest

from app import create_app, db
from app.cache import cache
from app.embeddings import get_model
from app.query_parser import reset_lexicon


@pytest.fixture(scope="session")
def app():
    # Avoid a race between the background warm-up thread and the first test.
    get_model()
    application = create_app()
    application.config.update(TESTING=True)
    yield application
    db.close_pool()


@pytest.fixture()
def client(app):
    cache.clear()
    reset_lexicon()
    return app.test_client()


@pytest.fixture()
def product_count(app):
    row = db.fetch_one("SELECT count(*) AS n FROM products")
    return row["n"]
