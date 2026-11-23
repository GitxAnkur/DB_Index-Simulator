"""Application configuration, loaded from environment variables."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


class Config:
    BASE_DIR: Path = BASE_DIR
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL", "postgresql://localhost:5433/product_search"
    )
    EMBEDDING_MODEL: str = os.getenv(
        "EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
    )
    EMBEDDING_DIM: int = int(os.getenv("EMBEDDING_DIM", "384"))
    DATASET_PATH: Path = BASE_DIR / os.getenv(
        "DATASET_PATH", "synthetic_products_100000.csv"
    )
    CACHE_TTL_SECONDS: int = int(os.getenv("CACHE_TTL_SECONDS", "300"))
    CACHE_MAX_ENTRIES: int = int(os.getenv("CACHE_MAX_ENTRIES", "512"))
    HNSW_EF_SEARCH: int = int(os.getenv("HNSW_EF_SEARCH", "100"))
    FLASK_HOST: str = os.getenv("FLASK_HOST", "127.0.0.1")
    FLASK_PORT: int = int(os.getenv("FLASK_PORT", "5001"))
    FLASK_DEBUG: bool = os.getenv("FLASK_DEBUG", "0") == "1"
    DATA_DIR: Path = BASE_DIR / "data"
    DOCS_DIR: Path = BASE_DIR / "docs"
    VALIDATION_JSON: Path = BASE_DIR / "data" / "dataset_validation.json"
    # Number of products shown in the application; 5 or 10 in the UI.
    ALLOWED_LIMITS = (5, 10)
    MIN_BENCHMARK_REPETITIONS = 5
    MAX_BENCHMARK_REPETITIONS = 20


class TestConfig(Config):
    TESTING = True
    CACHE_TTL_SECONDS = 60
