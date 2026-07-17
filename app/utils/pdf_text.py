"""
utils/pdf_text.py
------------------
Extracts a Certificate ID (e.g. "CERT-2026-000001") from the visible
text of an uploaded PDF.

WHY THIS EXISTS: SHA-256 has the avalanche property -- changing even one
byte of a file produces a completely unrelated hash. That means a
"verify by file" flow that ONLY looks up certificates by exact file_hash
match can NEVER distinguish "this is a tampered copy of certificate X"
from "this file is unrelated to any certificate we've issued" -- both
simply fail to find any row. Both would incorrectly report
"Certificate Not Found" instead of "Tampered Certificate", which defeats
one of the two required verification paths.

The fix: real certificate PDFs have their Certificate ID printed as
visible text on the document (that's the whole point of putting an ID
on a certificate). We extract that text and use the ID to look up the
ORIGINAL record, then compare hashes to detect tampering -- rather than
relying on the file hash alone to find the record in the first place.
"""

import logging
import re

logger = logging.getLogger(__name__)

CERTIFICATE_ID_PATTERN = re.compile(r"CERT-\d{4}-\d{6}")


def extract_certificate_id_from_pdf(file_bytes):
    """
    Attempt to find a Certificate ID string within a PDF's extractable
    text content.

    Args:
        file_bytes (bytes): raw PDF file content.

    Returns:
        str | None: the first matching Certificate ID found (e.g.
            "CERT-2026-000001"), or None if no extractable text
            contained a match (e.g. a scanned/image-only PDF, a
            corrupted file, or a genuinely unrelated document).

    Note: this deliberately never raises on a malformed/unreadable PDF --
    text extraction failing is a normal, expected outcome (not every
    PDF has a machine-readable text layer), and the caller falls back
    to exact file_hash matching in that case.
    """
    try:
        from pypdf import PdfReader
        from io import BytesIO

        reader = PdfReader(BytesIO(file_bytes))
        for page in reader.pages:
            text = page.extract_text() or ""
            match = CERTIFICATE_ID_PATTERN.search(text)
            if match:
                return match.group(0)
    except Exception:
        # Any failure here (encrypted PDF, corrupted file, missing
        # dependency, etc.) just means "couldn't extract an ID" -- not a
        # reason to break the verification request.
        logger.debug("Could not extract text from uploaded PDF for certificate ID detection", exc_info=True)

    return None
