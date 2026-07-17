"""
auth/models.py
--------------
Admin account model. Passwords are NEVER stored in plaintext -- only a
salted PBKDF2-SHA256 hash (via Werkzeug, the same library Flask itself
depends on, so no extra dependency is needed for password hashing).
"""

from datetime import datetime

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db


class Admin(db.Model, UserMixin):
    """
    Represents an admin user who can log in and manage students/certificates.

    UserMixin (from Flask-Login) supplies is_authenticated, is_active,
    is_anonymous, and get_id() so this class works directly with
    Flask-Login's login_user()/current_user machinery.
    """

    __tablename__ = "admins"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    full_name = db.Column(db.String(100), nullable=False)
    is_active_flag = db.Column("is_active", db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    last_login_at = db.Column(db.DateTime, nullable=True)

    def set_password(self, raw_password):
        """Hash and store a new password. Never store raw_password anywhere else."""
        self.password_hash = generate_password_hash(raw_password, method="pbkdf2:sha256")

    def check_password(self, raw_password):
        """Verify a plaintext password attempt against the stored hash."""
        return check_password_hash(self.password_hash, raw_password)

    # --- Flask-Login required overrides ---
    @property
    def is_active(self):
        # Overrides UserMixin's default (always True) with our real
        # is_active_flag column, so a deactivated admin account cannot
        # log in even with the correct password.
        return self.is_active_flag

    def get_id(self):
        return str(self.id)

    def __repr__(self):
        return f"<Admin id={self.id} username={self.username!r}>"
