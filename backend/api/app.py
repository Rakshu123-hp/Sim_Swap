"""Flask application factory.

Run locally:   python -m backend.api.app
Serves the plain-JS dashboard from frontend/ at / too, so the whole demo runs
from one process.
"""

import atexit
import os
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

from backend.api.routes import bp
from backend.db import models
from backend.demo_traffic import DemoTrafficManager

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
DEV_SECRET = "dev-only-secret-change-me"


def create_app(test_config=None):
    load_dotenv()

    app = Flask(__name__, static_folder=str(FRONTEND_DIR), static_url_path="")
    if test_config:
        app.config.update(test_config)

    app.config["JWT_SECRET_KEY"] = os.getenv("JWT_SECRET_KEY", DEV_SECRET)
    CORS(app)

    models.init_db()
    app.register_blueprint(bp)

    demo = DemoTrafficManager.from_env()
    app.extensions["demo_traffic"] = demo
    if test_config:
        # tests can override enabled/interval via config
        demo.enabled = bool(test_config.get("ENABLE_DEMO_TRAFFIC", demo.enabled))
        demo.interval = int(test_config.get("DEMO_TRAFFIC_INTERVAL", demo.interval))
        demo.rate = int(test_config.get("DEMO_TRAFFIC_RATE", demo.rate))
    demo.start()
    if demo.enabled:
        atexit.register(demo.stop)

    @app.get("/")
    def index():
        return send_from_directory(FRONTEND_DIR, "index.html")

    @app.errorhandler(404)
    def not_found(_exc):
        if request.path.startswith("/api/"):
            return jsonify(error="Endpoint not found"), 404
        return send_from_directory(FRONTEND_DIR, "index.html")

    @app.errorhandler(500)
    def server_error(_exc):
        return jsonify(error="Internal server error"), 500

    return app


if __name__ == "__main__":
    create_app().run(host="0.0.0.0", port=5000, debug=False)