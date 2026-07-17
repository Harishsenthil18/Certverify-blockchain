"""
utils/logger.py
----------------
Central logging configuration. Logs go to both the console (useful in
development) and a rotating file under logs/app.log (so a college-demo
laptop doesn't accumulate an unbounded log file over a semester).
"""

import logging
import os
from logging.handlers import RotatingFileHandler


def setup_logging(app):
    """
    Configure Flask's app.logger (and the root logger) with a console
    handler and a rotating file handler.

    Args:
        app (Flask): the application instance, already carrying its
            final config (LOG_FOLDER, LOG_FILE, DEBUG).
    """
    os.makedirs(app.config["LOG_FOLDER"], exist_ok=True)

    log_format = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    )

    file_handler = RotatingFileHandler(
        app.config["LOG_FILE"], maxBytes=2 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(log_format)
    file_handler.setLevel(logging.INFO)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_format)
    console_handler.setLevel(logging.DEBUG if app.debug else logging.INFO)

    # Avoid duplicate handlers if setup_logging() is ever called twice
    # (e.g. under a reloader) -- clear first.
    app.logger.handlers.clear()
    app.logger.addHandler(file_handler)
    app.logger.addHandler(console_handler)
    app.logger.setLevel(logging.INFO)
    app.logger.propagate = False

    # Also attach to the root logger so modules that use
    # logging.getLogger(__name__) directly (e.g. app/blockchain/*.py,
    # which have no knowledge of the Flask app) still get their messages
    # routed to the same handlers.
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
    root_logger.setLevel(logging.INFO)

    app.logger.info("Logging initialized. Log file: %s", app.config["LOG_FILE"])
