"""
config.py
---------
Central configuration, loaded from environment variables (via a .env
file in development). Never hardcode secrets/credentials directly in
code -- this is a basic but important security practice we want to
demonstrate even in a college mini project.
"""

import os
from urllib.parse import quote_plus
from datetime import timedelta

from dotenv import load_dotenv

# Load .env file (if present) into os.environ. In production, real
# environment variables (set by the OS/hosting platform) take
# precedence and this call is a harmless no-op if no .env file exists.
load_dotenv()


def _env_bool(key, default=False):
    """Parse an environment variable as a boolean ('true'/'1'/'yes')."""
    value = os.environ.get(key)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


class Config:
    """Base configuration shared by all environments."""

    # --- Security ---
    SECRET_KEY = os.environ.get("SECRET_KEY")
    if not SECRET_KEY:
        # Fail loudly in any environment where SECRET_KEY wasn't set,
        # rather than silently falling back to a guessable default --
        # an unset/weak SECRET_KEY breaks session security and CSRF
        # token integrity.
        raise RuntimeError(
            "SECRET_KEY environment variable is not set. "
            "Create a .env file (see .env.example) with a strong random SECRET_KEY."
        )

    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = None  # tokens don't expire mid-session

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    # Only send session cookies over HTTPS in production; allow HTTP in
    # local development so the app is usable without a TLS cert.
    SESSION_COOKIE_SECURE = _env_bool("SESSION_COOKIE_SECURE", default=False)
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)
    REMEMBER_COOKIE_DURATION = timedelta(days=14)
    REMEMBER_COOKIE_HTTPONLY = True

    # --- Database (MySQL via PyMySQL) ---
    DB_USER = os.environ.get("DB_USER", "certverify_app")
    DB_PASSWORD = os.environ.get("DB_PASSWORD", "")
    DB_HOST = os.environ.get("DB_HOST", "localhost")
    DB_PORT = os.environ.get("DB_PORT", "3306")
    DB_NAME = os.environ.get("DB_NAME", "certverify_db")

    SQLALCHEMY_DATABASE_URI = (
    f"mysql+pymysql://{DB_USER}:{quote_plus(DB_PASSWORD)}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    "?charset=utf8mb4"
)
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,   # detects and replaces stale/dropped DB connections
        "pool_recycle": 3600,    # recycle connections older than 1 hour
    }

    # Raw PyMySQL connection settings for the blockchain repository, which
    # intentionally talks to MySQL directly (not via the ORM) -- see
    # app/blockchain/repository.py for why this module is kept
    # framework/ORM-agnostic on purpose.
    BLOCKCHAIN_DB = {
        "host": DB_HOST,
        "port": int(DB_PORT),
        "user": DB_USER,
        "password": DB_PASSWORD,
        "database": DB_NAME,
        "charset": "utf8mb4",
    }

    # --- File uploads ---
    BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
    UPLOAD_FOLDER = os.path.join(BASE_DIR, "app", "uploads", "certificates")
    QR_CODE_FOLDER = os.path.join(BASE_DIR, "app", "static", "qrcodes")
    ALLOWED_EXTENSIONS = {"pdf"}
    MAX_CONTENT_LENGTH = 10 * 1024 * 1024  # 10 MB hard cap enforced by Flask itself

    # --- Logging ---
    LOG_FOLDER = os.path.join(BASE_DIR, "logs")
    LOG_FILE = os.path.join(LOG_FOLDER, "app.log")

    # --- App-specific ---
    VERIFICATION_BASE_URL = os.environ.get(
        "VERIFICATION_BASE_URL", "http://localhost:5000/verify"
    )  # used to build the URL embedded in each certificate's QR code


class DevelopmentConfig(Config):
    DEBUG = True
    SQLALCHEMY_ECHO = _env_bool("SQLALCHEMY_ECHO", default=False)


class TestingConfig(Config):
    """Used by the automated test suite. Overrides the DB to an
    in-memory SQLite database so tests run without a real MySQL server,
    and disables CSRF so test clients can POST forms without needing to
    scrape a CSRF token first."""
    TESTING = True
    DEBUG = False
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_ENGINE_OPTIONS = {}


class ProductionConfig(Config):
    DEBUG = False
    SESSION_COOKIE_SECURE = True


CONFIG_MAP = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}


def get_config(env_name=None):
    """Return the Config class matching FLASK_ENV (or the given name),
    defaulting to development if unset/unrecognized."""
    env_name = env_name or os.environ.get("FLASK_ENV", "development")
    return CONFIG_MAP.get(env_name, DevelopmentConfig)
