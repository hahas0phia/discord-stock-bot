"""
WSGI application wrapper for Gunicorn in production.
This allows the Flask app to run on Oracle Cloud App Container Runtime.
"""
import os
import sys
from dotenv import load_dotenv

# Load environment variables from .env file (if it exists locally)
load_dotenv()

# Import the Flask app and initialize database
from main import _flask_app, init_db, bot

# Initialize database on startup
try:
    init_db()
    print("✅ Database initialized")
except Exception as e:
    print(f"⚠️ Database initialization warning: {e}")

# Export the Flask app for Gunicorn
app = _flask_app

# Run Discord bot in background (started by main.py on import)
print("✅ Discord bot background tasks initialized")
print(f"✅ Flask app ready on port {os.getenv('PORT', 8080)}")
