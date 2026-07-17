"""
students/models.py
-------------------
Student model. A student may have zero or more certificates (see
Certificate.student_id FK in certificates/models.py).
"""

from datetime import datetime

from app.extensions import db


class Student(db.Model):
    __tablename__ = "students"

    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(100), nullable=False, index=True)
    roll_number = db.Column(db.String(50), unique=True, nullable=False, index=True)
    course = db.Column(db.String(100), nullable=False)
    year_of_passing = db.Column(db.Integer, nullable=False)
    email = db.Column(db.String(100), nullable=True)
    phone = db.Column(db.String(15), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # One-to-many: a student can have multiple certificates issued over
    # time (e.g. degree certificate + individual course certificates).
    # ON DELETE RESTRICT is enforced at the DB layer (schema.sql); here
    # we mirror that intent with passive_deletes so SQLAlchemy doesn't
    # try to null out certificates.student_id on its own.
    certificates = db.relationship(
        "Certificate", backref="student", lazy="dynamic", passive_deletes=True
    )

    def __repr__(self):
        return f"<Student id={self.id} roll_number={self.roll_number!r}>"

    def to_dict(self):
        return {
            "id": self.id,
            "full_name": self.full_name,
            "roll_number": self.roll_number,
            "course": self.course,
            "year_of_passing": self.year_of_passing,
            "email": self.email,
            "phone": self.phone,
        }
