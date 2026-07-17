"""
certificates/routes.py
------------------------
Certificate upload (with hashing + blockchain + duplicate prevention +
QR generation) and read-only listing/detail routes.

ATOMICITY: a new certificate touches THREE things that must all succeed
or all fail together:
  1. certificate_sequence row increment (new certificate_id)
  2. blockchain_blocks row insert (new block)
  3. certificates row insert
All three go through the SAME SQLAlchemy session/transaction. The
blockchain repository's save_block() is handed a cursor bound to that
same underlying DB-API connection (see app/extensions.py), so a single
db.session.commit() / db.session.rollback() covers everything. QR code
generation happens AFTER a successful commit, since it's a side effect
(a static file) rather than a DB write, and a QR failure shouldn't
un-issue an already-committed, valid certificate.
"""

import logging
import os

from flask import (
    Blueprint, current_app, flash, redirect, render_template,
    request, send_from_directory, url_for,
)
from flask_login import current_user, login_required

from app.blockchain.repository import BlockchainRepository
from app.certificates.forms import CertificateUploadForm
from app.certificates.id_generator import generate_certificate_id
from app.certificates.models import Certificate
from app.certificates.validators import (
    build_safe_storage_path, validate_file_size, validate_pdf_content,
)
from app.exceptions import AppError, DuplicateCertificateError
from app.extensions import db, get_write_cursor_for_current_transaction
from app.qr.generator import generate_certificate_qr
from app.students.models import Student
from app.utils.hashing import build_certificate_data_string, compute_combined_hash, sha256_bytes, sha256_string

logger = logging.getLogger(__name__)

certificates_bp = Blueprint("certificates", __name__, url_prefix="/certificates")


@certificates_bp.route("/", methods=["GET"])
@login_required
def list_certificates():
    query = request.args.get("q", "").strip()
    certs_query = Certificate.query.join(Student)
    if query:
        like_pattern = f"%{query}%"
        certs_query = certs_query.filter(
            db.or_(
                Certificate.certificate_id.ilike(like_pattern),
                Student.full_name.ilike(like_pattern),
                Student.roll_number.ilike(like_pattern),
            )
        )
    certificates = certs_query.order_by(Certificate.created_at.desc()).all()
    return render_template("certificates/list.html", certificates=certificates, query=query)


@certificates_bp.route("/<int:certificate_pk>", methods=["GET"])
@login_required
def view_certificate(certificate_pk):
    certificate = Certificate.query.get_or_404(certificate_pk)
    qr_filename = f"{certificate.certificate_id}.png"
    qr_exists = os.path.exists(os.path.join(current_app.config["QR_CODE_FOLDER"], qr_filename))
    return render_template(
        "certificates/detail.html",
        certificate=certificate,
        qr_filename=qr_filename if qr_exists else None,
    )


@certificates_bp.route("/upload", methods=["GET", "POST"])
@login_required
def upload_certificate():
    form = CertificateUploadForm()
    # Populate the student dropdown fresh on every request (GET or POST)
    # so a newly-added student shows up without a server restart.
    form.student_id.choices = [
        (s.id, f"{s.full_name} ({s.roll_number})")
        for s in Student.query.order_by(Student.full_name.asc()).all()
    ]

    if not form.student_id.choices:
        flash("Please add at least one student before uploading a certificate.", "warning")
        return redirect(url_for("students.add_student"))

    if form.validate_on_submit():
        try:
            certificate = _handle_certificate_upload(form)
        except AppError as exc:
            # Expected, "known" failure modes (duplicate, bad file, etc.)
            # -- log at warning level and show the message to the admin.
            logger.warning("Certificate upload rejected: %s", exc.message)
            flash(exc.message, "danger")
            return render_template("certificates/upload.html", form=form)
        except Exception:
            # Unexpected failure -- log full traceback, show a generic
            # message (never leak internals to the browser).
            logger.exception("Unexpected error during certificate upload")
            flash("An unexpected error occurred while uploading the certificate. Please try again.", "danger")
            return render_template("certificates/upload.html", form=form)

        flash(
            f"Certificate {certificate.certificate_id} uploaded and recorded on the blockchain successfully.",
            "success",
        )
        return redirect(url_for("certificates.view_certificate", certificate_pk=certificate.id))

    return render_template("certificates/upload.html", form=form)


def _handle_certificate_upload(form):
    """
    Core upload logic, isolated from the Flask route so it can be unit
    /integration tested directly and so the route function stays focused
    on HTTP concerns (rendering, flashing, redirecting).

    Returns:
        Certificate: the newly created and committed Certificate row.

    Raises:
        AppError (or a subclass): on any expected validation/business
            failure. The DB transaction and in-memory blockchain state
            are guaranteed to be rolled back before this function raises.
    """
    student = Student.query.get(form.student_id.data)
    if student is None:
        raise AppError("Selected student no longer exists.", status_code=400)

    # --- 1. Read and validate the uploaded file ---
    uploaded_file = form.certificate_file.data
    file_bytes = uploaded_file.read()
    validate_file_size(file_bytes, current_app.config["MAX_CONTENT_LENGTH"])
    validate_pdf_content(file_bytes)

    file_hash = sha256_bytes(file_bytes)

    # --- 2. Compute data_hash from certificate metadata (NOT including
    #        certificate_id -- see utils/hashing.py docstring for why) ---
    data_string = build_certificate_data_string(
        student_roll_number=student.roll_number,
        course_name=form.course_name.data.strip(),
        grade=form.grade.data.strip(),
        issue_date=form.issue_date.data,
    )
    data_hash = sha256_string(data_string)
    combined_hash = compute_combined_hash(data_hash, file_hash)

    # --- 3. Duplicate check BEFORE touching the certificate_sequence or
    #        blockchain, so a rejected duplicate never burns a
    #        certificate_id or creates orphaned state. ---
    existing = Certificate.query.filter_by(combined_hash=combined_hash).first()
    if existing is not None:
        raise DuplicateCertificateError(
            f"This exact certificate (same student, course, grade, issue date, "
            f"and file) has already been uploaded as {existing.certificate_id}."
        )

    blockchain_chain = current_app.extensions["blockchain_chain"]
    block_added = False

    try:
        # --- 4. Generate the certificate_id transactionally ---
        certificate_id = generate_certificate_id(session=db.session)

        # --- 5. Save the file to disk BEFORE the DB transaction, so a
        #        disk failure (full disk, permissions) aborts early
        #        without ever touching the database. If the DB
        #        transaction later fails, we delete this file in the
        #        except block below (no orphaned files). ---
        disk_path, safe_original_filename = build_safe_storage_path(
            current_app.config["UPLOAD_FOLDER"], file_hash, uploaded_file.filename
        )
        with open(disk_path, "wb") as f:
            f.write(file_bytes)

        # --- 6. Add the block to the IN-MEMORY chain and persist it via
        #        the repository, using a cursor bound to the SAME
        #        transaction as the upcoming certificate insert. ---
        block = blockchain_chain.add_block(combined_hash)
        block_added = True

        cursor = get_write_cursor_for_current_transaction()
        repo = BlockchainRepository(db_connection_provider=lambda: None)  # provider unused by save_block
        repo.save_block(block, cursor)

        # --- 7. Insert the certificate row itself ---
        certificate = Certificate(
            certificate_id=certificate_id,
            student_id=student.id,
            course_name=form.course_name.data.strip(),
            grade=form.grade.data.strip(),
            issue_date=form.issue_date.data,
            file_path=os.path.relpath(disk_path, current_app.config["UPLOAD_FOLDER"]),
            original_filename=safe_original_filename,
            file_hash=file_hash,
            data_hash=data_hash,
            combined_hash=combined_hash,
            block_id=block.db_id,
            uploaded_by=current_user.id,
        )
        db.session.add(certificate)
        db.session.commit()

    except Exception:
        db.session.rollback()
        if block_added:
            blockchain_chain.rollback_last_block(combined_hash)
        # Clean up the orphaned file if it was written before the failure.
        try:
            if "disk_path" in locals() and os.path.exists(disk_path):
                os.remove(disk_path)
        except OSError:
            logger.exception("Failed to clean up orphaned certificate file after a failed upload")
        raise

    logger.info(
        "Certificate uploaded: certificate_id=%s student_id=%d block_index=%d by admin_id=%d",
        certificate.certificate_id, student.id, block.index, current_user.id,
    )

    # --- 8. Generate QR code (post-commit, non-fatal on failure) ---
    try:
        generate_certificate_qr(
            certificate.certificate_id,
            current_app.config["VERIFICATION_BASE_URL"],
            current_app.config["QR_CODE_FOLDER"],
        )
    except Exception:
        logger.exception(
            "QR code generation failed for %s -- certificate was still saved successfully.",
            certificate.certificate_id,
        )

    return certificate


@certificates_bp.route("/download/<int:certificate_pk>")
@login_required
def download_certificate_file(certificate_pk):
    """Serve the stored PDF for a given certificate. Uses
    send_from_directory (not a raw open()) specifically because it
    performs its own path-traversal safety checks against the base
    directory -- defense in depth on top of validators.py's checks at
    upload time."""
    certificate = Certificate.query.get_or_404(certificate_pk)
    directory = os.path.dirname(os.path.join(current_app.config["UPLOAD_FOLDER"], certificate.file_path))
    filename = os.path.basename(certificate.file_path)
    return send_from_directory(directory, filename, as_attachment=True,
                                download_name=f"{certificate.certificate_id}.pdf")
