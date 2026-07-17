"""
utils/hashing.py
-----------------
Centralized SHA-256 hashing helpers. Every place in the app that needs
a hash (certificate upload, verification-by-ID, verification-by-file)
MUST use these exact functions, so the same inputs always deterministically
produce the same outputs -- any drift between "how upload computes a
hash" and "how verification recomputes it" would make every certificate
look tampered even when nothing changed.
"""

import hashlib


def sha256_bytes(data):
    """
    Compute the SHA-256 hex digest of raw bytes (e.g. an uploaded PDF's
    contents).

    Args:
        data (bytes): raw file content.

    Returns:
        str: 64-character lowercase hex digest.

    Raises:
        TypeError: if data is not bytes.
    """
    if not isinstance(data, (bytes, bytearray)):
        raise TypeError(f"sha256_bytes expects bytes, got {type(data)!r}")
    return hashlib.sha256(data).hexdigest()


def sha256_string(text):
    """
    Compute the SHA-256 hex digest of a UTF-8 encoded string.

    Args:
        text (str): input string.

    Returns:
        str: 64-character lowercase hex digest.
    """
    if not isinstance(text, str):
        raise TypeError(f"sha256_string expects str, got {type(text)!r}")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_certificate_data_string(student_roll_number, course_name, grade, issue_date):
    """
    Build the EXACT canonical string used to compute a certificate's
    data_hash. Field order and separators are fixed here, once, so this
    is the single source of truth both certificate upload and every
    future re-verification use to recompute data_hash from a
    certificate's current DB row.

    IMPORTANT: certificate_id is deliberately NOT included here. It is a
    freshly-generated, always-unique value assigned at upload time --
    if it were part of data_hash, then combined_hash could NEVER match
    an earlier upload's combined_hash, which would silently defeat the
    whole point of duplicate-certificate detection (re-uploading the
    exact same student+course+grade+date+file would always look "new").
    data_hash must depend only on content that is IDENTICAL when the
    same certificate is submitted twice.

    Args:
        student_roll_number (str)
        course_name (str)
        grade (str)
        issue_date (date | str): certificate issue date.

    Returns:
        str: canonical pipe-separated string, ready for sha256_string().
    """
    issue_date_str = issue_date.isoformat() if hasattr(issue_date, "isoformat") else str(issue_date)
    return "|".join([
        str(student_roll_number).strip(),
        str(course_name).strip(),
        str(grade).strip(),
        issue_date_str,
    ])


def compute_combined_hash(data_hash, file_hash):
    """
    Combine a certificate's data_hash and file_hash into one
    combined_hash -- this is the value stored (UNIQUE) on the
    certificates table and used as the blockchain block's
    certificate_hash. Deterministic field order (data_hash first) is
    important; swap it anywhere and every existing hash breaks.

    Args:
        data_hash (str): 64-char hex digest.
        file_hash (str): 64-char hex digest.

    Returns:
        str: 64-char hex digest.
    """
    return sha256_string(f"{data_hash}{file_hash}")
