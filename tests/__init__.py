"""
tests package init.

Sets required environment variables BEFORE any test module imports
anything from the `app` package -- app/config.py raises RuntimeError at
class-definition time if SECRET_KEY is unset, so this must run first.
Python guarantees this __init__.py executes before any submodule in the
package is imported (e.g. via `python -m unittest discover -s tests`).
"""

import os

os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_USER", "test")
os.environ.setdefault("DB_PASSWORD", "test")
os.environ.setdefault("DB_NAME", "test_db")
