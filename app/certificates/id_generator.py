"""
certificates/id_generator.py
------------------------------
Generates human-readable Certificate IDs like CERT-2026-000001, safely
under concurrent requests, using a row-level lock on certificate_sequence.
"""

from datetime import date

from app.certificates.models import CertificateSequence
from app.extensions import db


def generate_certificate_id(session=None, year=None):
    """
    Atomically generate the next Certificate ID for the given year
    (defaults to the current year).

    MUST be called within an already-open transaction that will be
    committed or rolled back together with the rest of the certificate
    upload (see certificates/routes.py) -- this function does NOT commit
    on its own, so that a duplicate-certificate rejection or blockchain
    failure later in the same request correctly rolls back this
    increment too (no "burned" certificate numbers on a failed upload).

    Uses SELECT ... FOR UPDATE (via SQLAlchemy's with_for_update()) to
    lock the year's row for the duration of the transaction, so two
    concurrent uploads in the same year can never read-then-write the
    same last_serial and collide on the same certificate_id.

    Note: SQLite (used by the automated test suite) does not implement
    real row-level locking -- with_for_update() is effectively a no-op
    there. This is fine for tests (SQLite serializes writers at the
    database level anyway) but the real concurrency guarantee is only
    meaningful against MySQL/InnoDB in production.

    Args:
        session: SQLAlchemy session to use (defaults to db.session).
        year (int | None): defaults to the current calendar year.

    Returns:
        str: e.g. "CERT-2026-000001"
    """
    session = session or db.session
    year = year or date.today().year

    sequence_row = (
        session.query(CertificateSequence)
        .filter_by(year=year)
        .with_for_update()
        .first()
    )

    if sequence_row is None:
        sequence_row = CertificateSequence(year=year, last_serial=0)
        session.add(sequence_row)
        session.flush()  # ensure the row exists before we lock/update it below

    sequence_row.last_serial += 1
    session.flush()  # push the increment into the transaction (not yet committed)

    return f"CERT-{year}-{sequence_row.last_serial:06d}"
