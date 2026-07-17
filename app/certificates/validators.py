"""
certificates/validators.py
---------------------------
File upload validation: type checking, size checking, and safe path
construction (path-traversal prevention) for certificate PDFs.
"""

import os
import uuid

from werkzeug.utils import secure_filename

from app.exceptions import FileTooLargeError, InvalidFileTypeError, UnsafeFilePathError

PDF_MAGIC_BYTES = b"%PDF-"


def is_allowed_extension(filename, allowed_extensions):
    """
    Check a filename's extension against an allow-list.

    Args:
        filename (str): the original uploaded filename.
        allowed_extensions (set[str]): e.g. {"pdf"}.

    Returns:
        bool
    """
    if not filename or "." not in filename:
        return False
    ext = filename.rsplit(".", 1)[1].lower()
    return ext in allowed_extensions


def validate_pdf_content(file_bytes):
    """
    Verify the uploaded file's actual bytes start with the PDF magic
    number (%PDF-), not just that its filename ends in .pdf.

    Why this matters: relying on the filename extension alone means
    someone could rename malware.exe to certificate.pdf and pass a
    naive extension check. Checking real file content is a much
    stronger (though still not bulletproof) guard.

    Args:
        file_bytes (bytes): the full file content.

    Raises:
        InvalidFileTypeError: if the content doesn't look like a real PDF.
    """
    if not file_bytes.startswith(PDF_MAGIC_BYTES):
        raise InvalidFileTypeError(
            "The uploaded file does not appear to be a valid PDF "
            "(missing PDF file signature)."
        )


def validate_file_size(file_bytes, max_bytes):
    """
    Args:
        file_bytes (bytes)
        max_bytes (int): maximum allowed size in bytes.

    Raises:
        FileTooLargeError: if the file exceeds max_bytes.
    """
    if len(file_bytes) > max_bytes:
        raise FileTooLargeError(
            f"File size ({len(file_bytes)} bytes) exceeds the maximum "
            f"allowed size ({max_bytes} bytes)."
        )
    if len(file_bytes) == 0:
        raise InvalidFileTypeError("Uploaded file is empty.")


def build_safe_storage_path(upload_folder, file_hash, original_filename):
    """
    Build a safe, collision-resistant, traversal-proof path to store an
    uploaded certificate under upload_folder.

    Design decisions:
      - The file is stored under a name DERIVED FROM ITS HASH, not the
        user-supplied original filename. This sidesteps path-traversal
        entirely (no attacker-controlled characters ever reach the
        filesystem path) and also naturally prevents filename collisions
        between different students' files.
      - werkzeug's secure_filename() is still applied to the ORIGINAL
        filename for display/storage purposes (original_filename column)
        as defense in depth, even though it never touches the disk path.
      - A short uuid4 suffix is added so that even if (extremely
        unlikely) two different uploads hashed to related-looking names,
        there's still no collision on disk.
      - We verify the FINAL resolved path is actually inside
        upload_folder before returning it -- this is the actual
        traversal check, not just "trust the construction logic."

    Args:
        upload_folder (str): absolute path to the certificates upload dir.
        file_hash (str): 64-char SHA-256 hex digest of the file content.
        original_filename (str): user-supplied filename (untrusted).

    Returns:
        tuple[str, str]: (absolute_disk_path, safe_original_filename)

    Raises:
        UnsafeFilePathError: if the resolved path would escape upload_folder.
    """
    safe_original_filename = secure_filename(original_filename) or "certificate.pdf"
    unique_suffix = uuid.uuid4().hex[:8]
    disk_filename = f"{file_hash}_{unique_suffix}.pdf"

    upload_folder_abs = os.path.abspath(upload_folder)
    candidate_path = os.path.abspath(os.path.join(upload_folder_abs, disk_filename))

    # The core traversal defense: no matter how disk_filename was built,
    # confirm the final resolved path is still WITHIN upload_folder.
    if os.path.commonpath([upload_folder_abs, candidate_path]) != upload_folder_abs:
        raise UnsafeFilePathError(
            "Resolved certificate storage path escapes the configured "
            "upload directory -- refusing to save file."
        )

    return candidate_path, safe_original_filename
