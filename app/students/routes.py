"""
students/routes.py
-------------------
Student CRUD routes, plus the main admin dashboard (shown here rather
than in its own blueprint since it's mostly student/certificate counts).
All routes require login (@login_required).
"""

import logging

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required
from sqlalchemy.exc import IntegrityError

from app.certificates.models import Certificate
from app.extensions import db
from app.students.forms import StudentForm
from app.students.models import Student
from app.verification.models import VerificationLog

logger = logging.getLogger(__name__)

students_bp = Blueprint("students", __name__, url_prefix="/students")


@students_bp.route("/dashboard")
@login_required
def dashboard():
    """Admin dashboard: summary counts + recent activity."""
    total_students = Student.query.count()
    total_certificates = Certificate.query.count()
    total_verifications = VerificationLog.query.count()
    recent_certificates = (
        Certificate.query.order_by(Certificate.created_at.desc()).limit(5).all()
    )
    recent_verifications = (
        VerificationLog.query.order_by(VerificationLog.verified_at.desc()).limit(5).all()
    )
    return render_template(
        "dashboard.html",
        total_students=total_students,
        total_certificates=total_certificates,
        total_verifications=total_verifications,
        recent_certificates=recent_certificates,
        recent_verifications=recent_verifications,
    )


@students_bp.route("/", methods=["GET"])
@login_required
def list_students():
    """List/search students. ?q= does a simple case-insensitive search
    across name and roll number."""
    query = request.args.get("q", "").strip()
    students_query = Student.query
    if query:
        like_pattern = f"%{query}%"
        students_query = students_query.filter(
            db.or_(
                Student.full_name.ilike(like_pattern),
                Student.roll_number.ilike(like_pattern),
            )
        )
    students = students_query.order_by(Student.full_name.asc()).all()
    return render_template("students/list.html", students=students, query=query)


@students_bp.route("/add", methods=["GET", "POST"])
@login_required
def add_student():
    form = StudentForm()
    if form.validate_on_submit():
        student = Student(
            full_name=form.full_name.data.strip(),
            roll_number=form.roll_number.data.strip(),
            course=form.course.data.strip(),
            year_of_passing=form.year_of_passing.data,
            email=form.email.data.strip() if form.email.data else None,
            phone=form.phone.data.strip() if form.phone.data else None,
        )
        db.session.add(student)
        try:
            db.session.commit()
        except IntegrityError:
            # Most likely cause: roll_number UNIQUE constraint violation
            # (a race between two admins, or the app-level check being
            # bypassed somehow) -- the DB is the final source of truth.
            db.session.rollback()
            logger.warning("Duplicate roll_number on add_student: %r", form.roll_number.data)
            flash("A student with this roll number already exists.", "danger")
            return render_template("students/add_edit.html", form=form, mode="add")

        logger.info("Student added: id=%d roll_number=%r", student.id, student.roll_number)
        flash(f"Student '{student.full_name}' added successfully.", "success")
        return redirect(url_for("students.list_students"))

    return render_template("students/add_edit.html", form=form, mode="add")


@students_bp.route("/<int:student_id>/edit", methods=["GET", "POST"])
@login_required
def edit_student(student_id):
    student = Student.query.get_or_404(student_id)
    form = StudentForm(obj=student)

    if form.validate_on_submit():
        student.full_name = form.full_name.data.strip()
        student.roll_number = form.roll_number.data.strip()
        student.course = form.course.data.strip()
        student.year_of_passing = form.year_of_passing.data
        student.email = form.email.data.strip() if form.email.data else None
        student.phone = form.phone.data.strip() if form.phone.data else None

        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("A student with this roll number already exists.", "danger")
            return render_template("students/add_edit.html", form=form, mode="edit", student=student)

        logger.info("Student updated: id=%d", student.id)
        flash(f"Student '{student.full_name}' updated successfully.", "success")
        return redirect(url_for("students.list_students"))

    return render_template("students/add_edit.html", form=form, mode="edit", student=student)


@students_bp.route("/<int:student_id>/delete", methods=["POST"])
@login_required
def delete_student(student_id):
    student = Student.query.get_or_404(student_id)

    # A student with existing certificates must NOT be deletable -- this
    # mirrors the DB-level ON DELETE RESTRICT constraint, but we check
    # it here too so we can give a clear, friendly flash message instead
    # of letting a raw IntegrityError bubble up to the user.
    has_certificates = Certificate.query.filter_by(student_id=student.id).first() is not None
    if has_certificates:
        flash(
            f"Cannot delete '{student.full_name}': this student has issued "
            f"certificates. Certificate records must remain intact for audit purposes.",
            "danger",
        )
        return redirect(url_for("students.list_students"))

    db.session.delete(student)
    db.session.commit()
    logger.info("Student deleted: id=%d", student_id)
    flash("Student deleted.", "info")
    return redirect(url_for("students.list_students"))
