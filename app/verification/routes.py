"""
verification/routes.py
------------------------
Public-facing certificate verification -- by Certificate ID, or by
re-uploading the PDF. Deliberately NOT behind @login_required: this is
the whole point of the system (an employer or third party with no
account should be able to verify a certificate).

TAMPER DETECTION LOGIC (the heart of the whole project):
For a given certificate row, we:
  1. Recompute data_hash from the certificate's CURRENT database fields.
  2. Recompute file_hash from the CURRENT stored PDF (verify-by-ID path)
     or from the freshly uploaded PDF (verify-by-file path).
  3. Recompute combined_hash from those two.
  4. Look up the blockchain block whose certificate_hash matches the
     ORIGINAL combined_hash stored on the certificate row.
  5. Compare: does the freshly recomputed combined_hash match the
     block's protected certificate_hash? And is that block (and the
     whole chain) still internally valid?
If any of those checks fail, the result is TAMPERED, not just "invalid" --
we want to be able to say precisely why in the admin-facing logs.
"""

import logging
import os

from flask import Blueprint, current_app, flash, render_template, request

from app.certificates.models import Certificate
from app.certificates.validators import validate_pdf_content
from app.exceptions import InvalidFileTypeError
from app.extensions import db
from app.utils.hashing import build_certificate_data_string, compute_combined_hash, sha256_bytes, sha256_string
from app.verification.forms import VerifyByFileForm, VerifyByIdForm
from app.verification.models import VerificationLog

logger = logging.getLogger(__name__)

verification_bp = Blueprint("verification", __name__, url_prefix="/verify")


def _recompute_certificate_hashes(certificate, file_bytes=None):
    """
    Recompute data_hash, file_hash, and combined_hash for a certificate
    row RIGHT NOW, from its current DB fields (and either the file bytes
    supplied by the caller, e.g. a freshly uploaded PDF, or the file
    currently stored on disk for that certificate).

    Args:
        certificate (Certificate): the DB row to recompute from.
        file_bytes (bytes | None): if provided (verify-by-file path),
            used directly. If None (verify-by-ID path), the certificate's
            own stored file on disk is read instead.

    Returns:
        tuple[str, str, str]: (data_hash, file_hash, combined_hash)

    Raises:
        FileNotFoundError: if file_bytes is None and the stored file is
            missing from disk (a serious integrity problem worth
            surfacing distinctly from "tampered").
    """
    student = certificate.student  # backref from Student.certificates

    data_string = build_certificate_data_string(
        student_roll_number=student.roll_number,
        course_name=certificate.course_name,
        grade=certificate.grade,
        issue_date=certificate.issue_date,
    )
    data_hash = sha256_string(data_string)

    if file_bytes is None:
        disk_path = os.path.join(current_app.config["UPLOAD_FOLDER"], certificate.file_path)
        with open(disk_path, "rb") as f:
            file_bytes = f.read()

    file_hash = sha256_bytes(file_bytes)
    combined_hash = compute_combined_hash(data_hash, file_hash)
    return data_hash, file_hash, combined_hash


def _check_certificate_against_blockchain(certificate, recomputed_combined_hash):
    """
    Given a certificate row and a freshly recomputed combined_hash,
    determine VALID vs TAMPERED by cross-checking against the blockchain.

    Returns:
        tuple[str, str]: (result, reason) where result is "VALID" or
            "TAMPERED", and reason is a human-readable explanation
            (useful for admin logs; the public result page keeps this
            vague on purpose -- see the route functions below).
    """
    blockchain_chain = current_app.extensions["blockchain_chain"]

    # Step 1: does the freshly recomputed hash match what was ORIGINALLY
    # stored on the certificate row at upload time?
    if recomputed_combined_hash != certificate.combined_hash:
        return "TAMPERED", (
            f"Recomputed combined_hash ({recomputed_combined_hash[:12]}...) does not "
            f"match the certificate's originally stored combined_hash "
            f"({certificate.combined_hash[:12]}...). The certificate's DB record "
            f"or file has been altered since it was issued."
        )

    # Step 2: does a block actually exist for this certificate_hash, and
    # is that block (and the surrounding chain) internally consistent?
    block = blockchain_chain.find_block_by_certificate_hash(certificate.combined_hash)
    if block is None:
        return "TAMPERED", (
            f"No blockchain block found for combined_hash "
            f"{certificate.combined_hash[:12]}... -- the certificate row exists "
            f"but has no corresponding chain record (possible direct DB tampering "
            f"that deleted or never created the block)."
        )

    if not block.is_hash_valid():
        return "TAMPERED", (
            f"Block {block.index} (protecting this certificate) failed its own "
            f"self-consistency check -- its stored current_hash does not match "
            f"a fresh recomputation."
        )

    is_chain_valid, chain_reason = blockchain_chain.is_chain_valid()
    if not is_chain_valid:
        return "TAMPERED", f"The blockchain as a whole failed validation: {chain_reason}"

    return "VALID", "All checks passed: file, data, and blockchain record are consistent."


def _log_verification_attempt(certificate_id, method, result):
    """Persist a VerificationLog row. Never let a logging failure break
    the verification response itself -- log-and-continue on error."""
    try:
        log_entry = VerificationLog(
            certificate_id=certificate_id,
            verification_method=method,
            result=result,
            ip_address=request.remote_addr,
            user_agent=request.headers.get("User-Agent", "")[:255],
        )
        db.session.add(log_entry)
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception("Failed to write verification log (verification result was still returned to the user)")


@verification_bp.route("/", methods=["GET"])
def verify_home():
    """Landing page offering both verification methods."""
    id_form = VerifyByIdForm()
    file_form = VerifyByFileForm()
    return render_template("verification/verify.html", id_form=id_form, file_form=file_form)


@verification_bp.route("/<certificate_id>", methods=["GET"])
def verify_by_id_direct(certificate_id):
    """Direct-link verification, e.g. the URL embedded in a certificate's
    QR code: /verify/CERT-2026-000001"""
    return _run_id_verification(certificate_id)


@verification_bp.route("/by-id", methods=["POST"])
def verify_by_id():
    form = VerifyByIdForm()
    if not form.validate_on_submit():
        flash("Please enter a valid Certificate ID (format CERT-YYYY-NNNNNN).", "danger")
        return render_template("verification/verify.html", id_form=form, file_form=VerifyByFileForm())
    return _run_id_verification(form.certificate_id.data.strip())


def _run_id_verification(certificate_id):
    certificate = Certificate.query.filter_by(certificate_id=certificate_id).first()

    if certificate is None:
        _log_verification_attempt(certificate_id, "ID", "NOT_FOUND")
        logger.info("Verification (by ID) NOT_FOUND: %r", certificate_id)
        return render_template(
            "verification/result.html", result="NOT_FOUND", certificate=None, certificate_id=certificate_id,
        )

    try:
        _, _, recomputed_combined_hash = _recompute_certificate_hashes(certificate)
    except FileNotFoundError:
        logger.error("Stored certificate file missing from disk for %s", certificate_id)
        _log_verification_attempt(certificate_id, "ID", "TAMPERED")
        return render_template(
            "verification/result.html", result="TAMPERED", certificate=certificate, certificate_id=certificate_id,
        )

    result, reason = _check_certificate_against_blockchain(certificate, recomputed_combined_hash)
    logger.info("Verification (by ID) %s: %r -- %s", result, certificate_id, reason)
    _log_verification_attempt(certificate_id, "ID", result)

    return render_template(
        "verification/result.html", result=result, certificate=certificate, certificate_id=certificate_id,
    )


@verification_bp.route("/by-file", methods=["POST"])
def verify_by_file():
    form = VerifyByFileForm()
    if not form.validate_on_submit():
        flash("Please choose a valid PDF file to verify.", "danger")
        return render_template("verification/verify.html", id_form=VerifyByIdForm(), file_form=form)

    file_bytes = form.certificate_file.data.read()

    try:
        validate_pdf_content(file_bytes)
    except InvalidFileTypeError as exc:
        flash(exc.message, "danger")
        return render_template("verification/verify.html", id_form=VerifyByIdForm(), file_form=form)

    uploaded_file_hash = sha256_bytes(file_bytes)

    # --- Two-tier lookup strategy ---
    # Tier 1: try to read a Certificate ID printed as visible text on the
    # PDF itself (real certificate templates print their ID on the
    # document). This is what lets us correctly report TAMPERED for a
    # certificate whose content was edited -- if we only matched on exact
    # file_hash, an edited file's hash would be completely unrelated to
    # the original (SHA-256 avalanche effect), and we'd wrongly report
    # NOT_FOUND instead of TAMPERED.
    from app.utils.pdf_text import extract_certificate_id_from_pdf
    extracted_certificate_id = extract_certificate_id_from_pdf(file_bytes)

    certificate = None
    if extracted_certificate_id:
        certificate = Certificate.query.filter_by(certificate_id=extracted_certificate_id).first()

    if certificate is None:
        # Tier 2 fallback: no readable ID text (e.g. scanned/image-only
        # PDF) -- fall back to an exact file_hash match, which still
        # correctly identifies an UNMODIFIED certificate file.
        certificate = Certificate.query.filter_by(file_hash=uploaded_file_hash).first()

    if certificate is None:
        _log_verification_attempt(None, "FILE", "NOT_FOUND")
        logger.info("Verification (by file) NOT_FOUND: file_hash=%s extracted_id=%r",
                     uploaded_file_hash, extracted_certificate_id)
        return render_template(
            "verification/result.html", result="NOT_FOUND", certificate=None, certificate_id=None,
        )

    _, _, recomputed_combined_hash = _recompute_certificate_hashes(certificate, file_bytes=file_bytes)
    result, reason = _check_certificate_against_blockchain(certificate, recomputed_combined_hash)
    logger.info("Verification (by file) %s: %r -- %s", result, certificate.certificate_id, reason)
    _log_verification_attempt(certificate.certificate_id, "FILE", result)

    return render_template(
        "verification/result.html", result=result, certificate=certificate, certificate_id=certificate.certificate_id,
    )
