"""
verification/models.py
-----------------------
VerificationLog model. Deliberately has NO foreign key to certificates
-- a verification attempt for a certificate_id that doesn't exist must
still be logged (that's the NOT_FOUND case), which a strict FK would
prevent unless made nullable in a way that adds no real benefit here.
See Phase 2's schema.sql for the original reasoning.
"""

from datetime import datetime

from app.extensions import db


class VerificationLog(db.Model):
    __tablename__ = "verification_logs"

    id = db.Column(db.BigInteger, primary_key=True)
    certificate_id = db.Column(db.String(20), nullable=True, index=True)
    verification_method = db.Column(db.Enum("ID", "FILE", name="verification_method_enum"), nullable=False)
    result = db.Column(
        db.Enum("VALID", "TAMPERED", "NOT_FOUND", name="verification_result_enum"),
        nullable=False,
        index=True,
    )
    ip_address = db.Column(db.String(45), nullable=True)
    user_agent = db.Column(db.String(255), nullable=True)
    verified_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)

    def __repr__(self):
        return f"<VerificationLog id={self.id} result={self.result}>"
