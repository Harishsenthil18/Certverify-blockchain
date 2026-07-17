"""
tests/helpers.py
-----------------
Shared setup for Flask-level tests: builds a test app (SQLite in-memory
DB, CSRF disabled) and provides a helper to log in as a seeded admin.

IMPORTANT ENVIRONMENT NOTE: Config.SECRET_KEY raises RuntimeError if the
SECRET_KEY environment variable is unset at import time (see
app/config.py) -- we set a throwaway test value here, before app.config
(or anything importing it) is ever imported, via tests/__init__.py.
"""

import os

# Must be set BEFORE `import app.config` happens anywhere (including
# transitively via `from app import create_app`) -- see app/config.py's
# fail-loud SECRET_KEY check. tests/__init__.py also sets this as a
# second line of defense for test runners that import test modules
# directly rather than importing the tests package first.
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_USER", "test")
os.environ.setdefault("DB_PASSWORD", "test")
os.environ.setdefault("DB_NAME", "test_db")

from app import create_app
from app.auth.models import Admin
from app.extensions import db


def make_test_app():
    """
    Build a Flask app configured for testing: SQLite in-memory database,
    CSRF disabled (see TestingConfig), all tables created fresh.

    NOTE ON THE BLOCKCHAIN: create_app() will attempt a real PyMySQL
    connection during _init_blockchain() (to app.config['BLOCKCHAIN_DB'],
    pointed at DB_HOST=localhost by default). In a CI/test environment
    without a real MySQL server, this fails gracefully by design (see
    app/__init__.py's _init_blockchain try/except) and the app starts
    with an EMPTY in-memory Blockchain instead of crashing. Tests that
    need a non-empty chain must call `chain.create_genesis_block()`
    themselves after app creation (see test_certificates.py).

    Returns:
        Flask: a configured test app instance.
    """
    app = create_app("testing")
    with app.app_context():
        db.create_all()
    return app


def seed_admin(app, username="testadmin", password="Test@1234", full_name="Test Admin"):
    """Create and commit a real Admin row with a real password hash,
    inside the given app's context."""
    with app.app_context():
        admin = Admin(username=username, full_name=full_name)
        admin.set_password(password)
        db.session.add(admin)
        db.session.commit()
        return admin.id


def login(client, username="testadmin", password="Test@1234"):
    """POST the login form via a Flask test client. Returns the response."""
    return client.post(
        "/auth/login",
        data={"username": username, "password": password},
        follow_redirects=True,
    )
