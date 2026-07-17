"""
run.py
------
Development entry point. In production, use a real WSGI server (e.g.
gunicorn) pointing at app:create_app() instead of running this file
directly -- see the Deployment Guide (generated in a later phase).
"""

from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=app.config.get("DEBUG", False))
