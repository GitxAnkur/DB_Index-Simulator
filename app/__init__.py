"""Flask application factory."""
from __future__ import annotations

import logging
import threading

from flask import Flask, jsonify, request

from . import db
from .cache import configure_cache
from .config import Config
from .embeddings import get_model

__version__ = "1.0.0"


def create_app(config_object=Config) -> Flask:
    app = Flask(
        __name__,
        static_folder=str(Config.BASE_DIR / "static"),
        template_folder=str(Config.BASE_DIR / "templates"),
    )
    app.config.from_object(config_object)
    app.config["JSON_SORT_KEYS"] = False
    configure_cache(
        app.config.get("CACHE_MAX_ENTRIES", Config.CACHE_MAX_ENTRIES),
        app.config.get("CACHE_TTL_SECONDS", Config.CACHE_TTL_SECONDS),
    )

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    try:
        db.init_pool(app.config["DATABASE_URL"])
    except Exception as exc:  # health endpoint reports the problem
        app.logger.error("Database pool initialisation failed: %s", exc)

    # Load the embedding model in the background so the first semantic search
    # does not pay the one-time model-loading cost.
    def _warm_model():
        try:
            get_model()
            app.logger.info("Sentence Transformers model warmed up")
        except Exception as exc:  # pragma: no cover - environment dependent
            app.logger.error("Model warm-up failed: %s", exc)

    threading.Thread(target=_warm_model, daemon=True).start()

    from .routes import api, pages

    app.register_blueprint(pages)
    app.register_blueprint(api)

    @app.errorhandler(404)
    def not_found(exc):
        if request.path.startswith("/api/"):
            return jsonify({"error": "Endpoint not found"}), 404
        return "Not found", 404

    @app.errorhandler(405)
    def method_not_allowed(exc):
        if request.path.startswith("/api/"):
            return jsonify({"error": "Method not allowed"}), 405
        return "Method not allowed", 405

    @app.errorhandler(500)
    def internal_error(exc):
        if request.path.startswith("/api/"):
            return jsonify({"error": "Internal server error"}), 500
        return "Internal server error", 500

    @app.after_request
    def headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        return response

    @app.get("/favicon.ico")
    def favicon():
        return "", 204

    return app
