"""
certificates/models.py
-----------------------
Certificate model (the row-level record of an issued certificate) and
CertificateSequence (a small helper table used to safely generate
human-readable IDs like CERT-2026-000001 under concurrent uploads).
"""

from datetime import datetime

from app.extensions import db


class Certificate(db.Model):
    __tablename__ = "certificates"

    id = db.Column(db.Integer, primary_key=True)
    certificate_id = db.Column(db.String(20), unique=True, nullable=False, index=True)
    student_id = db.Column(
        db.Integer,
        db.ForeignKey("students.id", ondelete="RESTRICT"),
        nullable=False,
    )
    course_name = db.Column(db.String(150), nullable=False)
    grade = db.Column(db.String(20), nullable=False)
    issue_date = db.Column(db.Date, nullable=False)

    file_path = db.Column(db.String(255), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)

    file_hash = db.Column(db.String(64), nullable=False, index=True)
    data_hash = db.Column(db.String(64), nullable=False)
    combined_hash = db.Column(db.String(64), unique=True, nullable=False, index=True)

    # References the persisted blockchain_blocks.id (that table is NOT an
    # ORM model on purpose -- see app/blockchain/repository.py -- so this
    # is a plain integer column, not a db.relationship()).
    block_id = db.Column(db.Integer, unique=True, nullable=False)

    uploaded_by = db.Column(
        db.Integer, db.ForeignKey("admins.id", ondelete="SET NULL"), nullable=True
    )
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def __repr__(self):
        return f"<Certificate id={self.id} certificate_id={self.certificate_id!r}>"

    def to_dict(self):
        return {
            "id": self.id,
            "certificate_id": self.certificate_id,
            "student_id": self.student_id,
            "course_name": self.course_name,
            "grade": self.grade,
            "issue_date": self.issue_date.isoformat() if self.issue_date else None,
            "file_hash": self.file_hash,
            "data_hash": self.data_hash,
            "combined_hash": self.combined_hash,
            "block_id": self.block_id,
        }


class CertificateSequence(db.Model):
    """
    One row per calendar year. Incremented transactionally (via
    SELECT...FOR UPDATE) when generating a new certificate_id, so two
    concurrent uploads in the same year can never collide on the same
    serial number.
    """
    __tablename__ = "certificate_sequence"

    year = db.Column(db.Integer, primary_key=True)
    last_serial = db.Column(db.Integer, nullable=False, default=0)
