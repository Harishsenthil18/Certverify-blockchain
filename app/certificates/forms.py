"""
certificates/forms.py
----------------------
WTForms form for uploading a new certificate.
"""

from datetime import date

from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField, FileRequired
from wtforms import DateField, SelectField, StringField, SubmitField
from wtforms.validators import DataRequired, Length, ValidationError


class CertificateUploadForm(FlaskForm):
    student_id = SelectField(
        "Student",
        coerce=int,
        validators=[DataRequired(message="Please select a student.")],
    )
    course_name = StringField(
        "Course Name",
        validators=[DataRequired(), Length(min=2, max=150)],
    )
    grade = StringField(
        "Grade",
        validators=[DataRequired(), Length(min=1, max=20)],
    )
    issue_date = DateField(
        "Issue Date",
        validators=[DataRequired()],
    )
    certificate_file = FileField(
        "Certificate PDF",
        validators=[
            FileRequired(message="Please choose a PDF file."),
            FileAllowed(["pdf"], message="Only PDF files are allowed."),
        ],
    )
    submit = SubmitField("Upload Certificate")

    def validate_issue_date(self, field):
        """A certificate cannot be issued in the future."""
        if field.data > date.today():
            raise ValidationError("Issue date cannot be in the future.")
