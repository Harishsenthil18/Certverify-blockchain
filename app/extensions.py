"""
extensions.py
-------------
Flask extension instances, created here (uninitialized) and bound to
the app later inside create_app() via extension.init_app(app). This is
the standard pattern that avoids circular imports between blueprints
and the app factory.

Also provides the connection helpers the blockchain repository needs.
The blockchain module (app/blockchain/*) is deliberately kept
independent of both Flask and SQLAlchemy (see Phase 3), so this file is
the ONLY place that bridges "Flask app config" -> "a real DB
connection" for blockchain persistence.
"""

import logging

import pymysql
import pymysql.cursors
from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect

db = SQLAlchemy()
login_manager = LoginManager()
csrf = CSRFProtect()

logger = logging.getLogger(__name__)


def make_blockchain_read_connection(app):
    """
    Open a NEW, independent PyMySQL connection (with DictCursor) for
    reading blocks -- used at application startup to load and validate
    the whole chain, and anywhere else we just need a read-only view
    that does not need to share a transaction with the ORM.

    A fresh connection per call (rather than a long-lived global one) is
    intentional and simple for a mini-project scope -- it avoids stale-
    connection issues and keeps the blockchain module's DB usage
    obviously separate from Flask-SQLAlchemy's own connection pool.

    Returns:
        pymysql.connections.Connection
    """
    cfg = app.config["BLOCKCHAIN_DB"]
    return pymysql.connect(
        host=cfg["host"],
        port=cfg["port"],
        user=cfg["user"],
        password=cfg["password"],
        database=cfg["database"],
        charset=cfg["charset"],
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,  # read-only usage; no transaction needed
    )


def get_write_cursor_for_current_transaction():
    """
    Return a plain (non-dict) DB-API cursor bound to the SAME underlying
    connection/transaction that the current Flask-SQLAlchemy session
    (db.session) is using.

    WHY THIS MATTERS: when a new certificate is uploaded, we must insert
    a `certificates` row (via the ORM) AND a `blockchain_blocks` row (via
    the framework-agnostic repository) as ONE atomic unit -- either both
    succeed, or neither does. The only way to guarantee that across two
    different code paths (ORM vs. raw repository) is to make sure they
    both write through the exact same DB-API connection, so a single
    db.session.commit() / db.session.rollback() covers both.

    SQLAlchemy exposes the underlying DBAPI connection differently across
    versions:
      - SQLAlchemy 1.4: Connection.connection (legacy proxy)
      - SQLAlchemy 2.0: Connection.connection.dbapi_connection is the
        "real" driver connection; .connection itself still works via a
        compatibility shim in most 2.0 installs.
    We try the more direct attribute first and fall back gracefully, so
    this keeps working regardless of which SQLAlchemy version is
    installed.

    Returns:
        A DB-API cursor object, ready for cursor.execute(...).
    """
    sa_connection = db.session.connection()
    dbapi_connection = getattr(sa_connection, "connection", None)
    # Unwrap one more level if this is a SQLAlchemy 2.0-style facade.
    dbapi_connection = getattr(dbapi_connection, "dbapi_connection", dbapi_connection)

    if dbapi_connection is None:
        raise RuntimeError(
            "Could not obtain the underlying DB-API connection from the "
            "current SQLAlchemy session -- cannot guarantee atomic "
            "certificate + blockchain block insertion."
        )
    return dbapi_connection.cursor()
