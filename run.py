#!/usr/bin/env python3
"""Run the Flask development server."""
from __future__ import annotations

from app import create_app
from app.config import Config

app = create_app()

if __name__ == "__main__":
    app.run(
        host=Config.FLASK_HOST,
        port=Config.FLASK_PORT,
        debug=Config.FLASK_DEBUG,
        use_reloader=False,
    )
