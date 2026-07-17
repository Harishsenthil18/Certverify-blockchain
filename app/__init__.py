"""
app/__init__.py
----------------
Flask application factory (create_app pattern). Centralizes:
  - extension initialization (db, login_manager, csrf)
  - blueprint registration
  - logging setup
  - global error handlers
  - blockchain startup: load all blocks from MySQL, rebuild the
    in-memory chain, and validate it -- BEFORE the app starts serving
    requests, so a corrupted/tampered chain is detected immediately on
    deploy/restart rather than silently discovered later.

IMPORTANT DESIGN NOTE: this module deliberately does NOT import Flask,
PyMySQL, or any of their dependents at MODULE (top) level -- only inside
create_app() and its helper functions. Python always executes a
package's __init__.py before importing any of its submodules, so if
Flask/PyMySQL imports lived at the top of this file, even an unrelated,
dependency-free import like `from app.blockchain.block import Block`
would require Flask and PyMySQL to be installed. That would break
Phase 3's core design goal: the blockchain module has zero framework
dependencies and must be unit-testable on its own. Keeping these imports
lazy (inside functions) preserves that property.
"""

import logging

logger = logging.getLogger(__name__)


def create_app(config_name=None):
    """
    Application factory. Using a factory (instead of a module-level
    `app = Flask(__name__)`) avoids circular imports between blueprints
    and lets the test suite spin up multiple independent app instances
    with different configs.

    Args:
        config_name (str | None): "development" | "testing" | "production".
            Defaults to the FLASK_ENV environment variable.

    Returns:
        Flask: a fully configured application instance.
    """
    from flask import Flask
    from app.config import get_config
    from app.utils.logger import setup_logging

    app = Flask(__name__)
    app.config.from_object(get_config(config_name))

    setup_logging(app)
    _init_extensions(app)
    _register_blueprints(app)
    _register_error_handlers(app)
    _init_blockchain(app)

    app.logger.info("Application created successfully (config=%s).", config_name or "development")
    return app




def _init_extensions(app):
    from app.extensions import csrf, db, login_manager

    db.init_app(app)
    csrf.init_app(app)

    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Please log in to access this page."
    login_manager.login_message_category = "warning"

    @login_manager.user_loader
    def load_user(user_id):
        from app.auth.models import Admin
        return Admin.query.get(int(user_id))


def _register_blueprints(app):
    from app.auth.routes import auth_bp
    from app.certificates.routes import certificates_bp
    from app.students.routes import students_bp
    from app.verification.routes import verification_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(students_bp)
    app.register_blueprint(certificates_bp)
    app.register_blueprint(verification_bp)

    @app.route("/")
    def index():
        from flask import redirect, url_for
        from flask_login import current_user
        if current_user.is_authenticated:
            return redirect(url_for("students.dashboard"))
        return redirect(url_for("verification.verify_home"))


def _register_error_handlers(app):
    """
    Global error handlers. Each handler:
      - logs appropriately (warning for expected/client errors, error/
        exception for unexpected server-side failures)
      - renders an HTML error page for normal browser requests
      - falls back to a minimal inline response if the error template
        itself is missing (defensive -- an error handler must never
        itself throw a TemplateNotFound and mask the original error)
      - returns JSON instead of HTML if the request looks like an API/
        AJAX call (Accept: application/json)
    """

    from flask import jsonify, render_template, request
    from app.exceptions import AppError
    from app.extensions import db

    def _wants_json():
        return request.accept_mimetypes["application/json"] >= request.accept_mimetypes["text/html"]

    def _render_error_page(template_name, status_code, message):
        if _wants_json():
            return jsonify(error=message), status_code
        try:
            return render_template(template_name, message=message), status_code
        except Exception:
            # Template not created yet (e.g. before Phase 5) -- fall back
            # to a minimal but still informative response rather than
            # crashing the error handler itself.
            return (
                f"<h1>Error {status_code}</h1><p>{message}</p>",
                status_code,
                {"Content-Type": "text/html"},
            )

    @app.errorhandler(AppError)
    def handle_app_error(error):
        app.logger.warning("AppError: %s", error.message)
        return _render_error_page("errors/generic.html", error.status_code, error.message)

    @app.errorhandler(400)
    def handle_bad_request(error):
        return _render_error_page("errors/400.html", 400, "Bad request.")

    @app.errorhandler(403)
    def handle_forbidden(error):
        app.logger.warning("403 Forbidden: %s %s", request.method, request.path)
        return _render_error_page("errors/403.html", 403, "You do not have permission to access this page.")

    @app.errorhandler(404)
    def handle_not_found(error):
        return _render_error_page("errors/404.html", 404, "The page you requested was not found.")

    @app.errorhandler(413)
    def handle_payload_too_large(error):
        app.logger.warning("413 Payload too large: %s %s", request.method, request.path)
        return _render_error_page(
            "errors/413.html", 413,
            f"File too large. Maximum allowed size is "
            f"{app.config['MAX_CONTENT_LENGTH'] // (1024 * 1024)} MB.",
        )

    @app.errorhandler(500)
    def handle_internal_error(error):
        app.logger.exception("500 Internal Server Error: %s %s", request.method, request.path)
        db.session.rollback()  # ensure a failed request never leaves a half-open transaction
        return _render_error_page("errors/500.html", 500, "An unexpected error occurred. Please try again.")

    @app.errorhandler(Exception)
    def handle_unexpected_error(error):
        # Last-resort catch-all for anything not already handled above.
        # This must NEVER leak a raw traceback to the browser.
        app.logger.exception("Unhandled exception: %s %s", request.method, request.path)
        db.session.rollback()
        return _render_error_page("errors/500.html", 500, "An unexpected error occurred. Please try again.")


def _init_blockchain(app):
    """
    Load all persisted blocks from MySQL, rebuild the in-memory
    Blockchain, and validate the whole chain -- once, at startup.

    The resulting Blockchain instance is stored on
    app.extensions["blockchain_chain"] so route handlers (certificate
    upload, verification) can access the SAME in-memory chain object for
    the lifetime of the process, via current_app.extensions["blockchain_chain"].

    If the chain fails validation, we do NOT crash the whole application
    (a tampered chain is a fact the app needs to be able to report to
    admins, not necessarily a reason the server can't start at all) --
    but we log it at CRITICAL level, very loudly, so it cannot be missed
    in the logs.

    If we cannot even CONNECT to the database at startup (e.g. running
    tooling before MySQL is configured, or first-time setup before
    schema.sql has been run), we log a clear warning and start with an
    EMPTY chain rather than crashing -- this keeps the app importable
    for tooling even before the DB is fully provisioned, while making it
    obvious in the logs that the chain isn't loaded.
    """
    from app.blockchain.chain import Blockchain
    from app.blockchain.repository import BlockchainRepository, RepositoryError
    from app.extensions import make_blockchain_read_connection

    blockchain_chain = Blockchain()
    app.extensions["blockchain_chain"] = blockchain_chain

    try:
        connection = make_blockchain_read_connection(app)
    except Exception as exc:
        app.logger.warning(
            "Could not connect to the database to load the blockchain at "
            "startup (%s). Starting with an EMPTY in-memory chain -- run "
            "database/schema.sql and confirm DB_* environment variables "
            "before issuing or verifying certificates.", exc,
        )
        return

    try:
        repo = BlockchainRepository(db_connection_provider=lambda: connection)
        blocks = repo.load_all_blocks()
    except RepositoryError as exc:
        app.logger.critical("Failed to load blockchain blocks from database: %s", exc)
        return
    finally:
        connection.close()

    if not blocks:
        app.logger.critical(
            "blockchain_blocks table is empty -- no Genesis Block found. "
            "Run database/schema.sql to initialize the chain before using the app."
        )
        return

    is_valid, reason = blockchain_chain.rebuild_chain_from_database(blocks)
    if is_valid:
        app.logger.info("Blockchain loaded and validated at startup: %d blocks, chain VALID.", len(blocks))
    else:
        app.logger.critical(
            "BLOCKCHAIN VALIDATION FAILED AT STARTUP: %s -- the chain has "
            "%d blocks loaded but is NOT internally consistent. This "
            "likely means the blockchain_blocks table was modified "
            "outside the application. Certificate verification results "
            "will reflect this until the issue is investigated.",
            reason, len(blocks),
        )
