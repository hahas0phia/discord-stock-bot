"""
Health check service for Discord Bot (optional standalone version).
Note: The main health check is now in main.py at /health endpoint.

This file is kept for backward compatibility and can be used as a standalone
health check service if needed.
"""
from flask import Flask, jsonify
import os
from datetime import datetime

app = Flask(__name__)

@app.route("/")
@app.route("/health")
def health():
    """Health check endpoint."""
    return jsonify({
        "status": "healthy",
        "service": "discord-bot",
        "timestamp": datetime.utcnow().isoformat()
    }), 200

@app.route("/ready")
def ready():
    """Readiness check - bot is ready to accept commands."""
    return jsonify({
        "status": "ready",
        "version": "1.0.0"
    }), 200

if __name__ == "__main__":
    port = int(os.environ.get("HEALTH_PORT", 8765))
    app.run(host="0.0.0.0", port=port, debug=False)
