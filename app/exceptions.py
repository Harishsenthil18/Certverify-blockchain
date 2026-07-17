"""
exceptions.py
-------------
Custom exception hierarchy for the application. Using specific exception
types (instead of generic Exception/ValueError everywhere) lets route
handlers and the global error handlers in app/__init__.py react
differently to different failure modes, and gives clearer log messages.
"""


class AppError(Exception):
    """Base class for all application-specific (expected) errors.
    Anything raised as an AppError is treated as a 'known' failure mode
    with a user-facing message; anything else bubbling up is treated as
    an unexpected bug and logged/handled as a 500."""

    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class InvalidFileTypeError(AppError):
    """Raised when an uploaded file's extension/content-type is not an
    allowed type (only .pdf is accepted for certificates)."""

    def __init__(self, message="Only PDF files are allowed."):
        super().__init__(message, status_code=400)


class FileTooLargeError(AppError):
    """Raised when an uploaded file exceeds the configured max size."""

    def __init__(self, message="File exceeds the maximum allowed size."):
        super().__init__(message, status_code=413)


class DuplicateCertificateError(AppError):
    """Raised when an uploaded certificate's combined_hash already exists
    in the certificates table (app-level guard; the DB's UNIQUE
    constraint on combined_hash is the ultimate source of truth)."""

    def __init__(self, message="This certificate has already been uploaded."):
        super().__init__(message, status_code=409)


class CertificateNotFoundError(AppError):
    """Raised when a certificate lookup (by ID or by file) finds nothing."""

    def __init__(self, message="Certificate not found."):
        super().__init__(message, status_code=404)


class UnsafeFilePathError(AppError):
    """Raised when a resolved file path would fall outside the configured
    upload directory (path traversal attempt, e.g. via '../../' in a
    filename before secure_filename() sanitization, or a symlink trick)."""

    def __init__(self, message="Invalid file path."):
        super().__init__(message, status_code=400)


class BlockchainIntegrityError(AppError):
    """Raised when the blockchain fails validation at a point where the
    application cannot safely continue (e.g. certificate upload attempted
    while the in-memory chain is known to be corrupted)."""

    def __init__(self, message="Blockchain integrity check failed."):
        super().__init__(message, status_code=500)
