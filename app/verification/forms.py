"""
verification/forms.py
----------------------
Two separate small forms for the two verification paths: by
Certificate ID, and by re-uploading the PDF.
"""

from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileRequired, FileField
from wtforms import StringField, SubmitField
from wtforms.validators import DataRequired, Length, Regexp


class VerifyByIdForm(FlaskForm):
    certificate_id = StringField(
        "Certificate ID",
        validators=[
            DataRequired(message="Please enter a Certificate ID."),
            Length(max=20),
            Regexp(r"^CERT-\d{4}-\d{6}$", message="Format must be CERT-YYYY-NNNNNN, e.g. CERT-2026-000001."),
        ],
    )
    submit = SubmitField("Verify")


class VerifyByFileForm(FlaskForm):
    certificate_file = FileField(
        "Certificate PDF",
        validators=[
            FileRequired(message="Please choose a PDF file to verify."),
            FileAllowed(["pdf"], message="Only PDF files are allowed."),
        ],
    )
    submit = SubmitField("Verify")
