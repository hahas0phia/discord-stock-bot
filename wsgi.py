"""
WSGI application wrapper for Gunicorn in production.
This allows the Flask app to run on Oracle Cloud App Container Runtime.
"""
import os
from dotenv import load_dotenv

# Load environment variables from .env file (if it exists locally)
load_dotenv()

# Import the Flask app and initialize database
from main import _flask_app, init_db, start_discord_bot

try:
    init_db()
    print("[WSGI] Database initialized")
except Exception as e:
    print(f"[WSGI] Database initialization warning: {e}")

try:
    if os.getenv("DISCORD_TOKEN"):
        start_discord_bot(background=True)
        print("[WSGI] Discord bot background thread started")
    else:
        print("[WSGI] DISCORD_TOKEN not set; Discord bot not started")
except Exception as e:
    print(f"[WSGI] Discord bot startup warning: {e}")

app = _flask_app
print(f"[WSGI] Flask app ready on port {os.getenv('PORT', 8080)}")
