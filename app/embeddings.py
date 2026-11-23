"""Sentence Transformers embedding service.

The model runs locally on CPU. No API keys or paid services are used. The
actual dimension is read from the loaded model and checked against the
database column definition.
"""
from __future__ import annotations

import threading
import time
from typing import Iterable

import numpy as np

from .config import Config

_model = None
_model_lock = threading.Lock()
_load_seconds: float | None = None


def get_model():
    global _model, _load_seconds
    if _model is None:
        with _model_lock:
            if _model is None:
                from sentence_transformers import SentenceTransformer

                started = time.perf_counter()
                _model = SentenceTransformer(Config.EMBEDDING_MODEL, device="cpu")
                _load_seconds = time.perf_counter() - started
    return _model


def model_status() -> dict:
    return {
        "name": Config.EMBEDDING_MODEL,
        "dimension": Config.EMBEDDING_DIM,
        "loaded": _model is not None,
        "load_seconds": round(_load_seconds, 3) if _load_seconds is not None else None,
    }


def model_info() -> dict:
    model = get_model()
    dim = int(model.get_sentence_embedding_dimension())
    return {
        "name": Config.EMBEDDING_MODEL,
        "dimension": dim,
        "expected_dimension": Config.EMBEDDING_DIM,
        "dimension_matches_schema": dim == Config.EMBEDDING_DIM,
        "device": "cpu",
        "load_seconds": round(_load_seconds, 3) if _load_seconds is not None else None,
        "normalized": True,
    }


def encode_query(text: str) -> tuple[np.ndarray, float]:
    started = time.perf_counter()
    vector = get_model().encode(
        [text],
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=False,
    )[0]
    elapsed_ms = (time.perf_counter() - started) * 1000
    return np.asarray(vector, dtype=np.float32), elapsed_ms


def encode_texts(texts: Iterable[str], batch_size: int = 128) -> np.ndarray:
    return get_model().encode(
        list(texts),
        batch_size=batch_size,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=True,
    )


def to_pgvector(vector: np.ndarray | list[float]) -> str:
    """Serialise a vector for pgvector's text input format."""
    arr = np.asarray(vector, dtype=np.float32).ravel()
    return "[" + ",".join(f"{float(x):.7f}" for x in arr) + "]"


def product_embedding_text(row: dict) -> str:
    """Compose the semantic document for one product.

    Fields are ordered from most to least descriptive. The original CSV fields
    remain unchanged in their own columns.
    """
    parts = [
        row.get("name") or "",
        row.get("category") or "",
        row.get("brand") or "",
        row.get("use_case") or "",
        row.get("specifications") or "",
        row.get("description") or "",
        row.get("tags") or "",
        row.get("color") or "",
    ]
    return " | ".join(str(p).strip() for p in parts if str(p).strip())
