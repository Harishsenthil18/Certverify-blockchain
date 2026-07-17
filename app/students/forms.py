"""
students/forms.py
------------------
WTForms form for adding/editing a student record.
"""

from datetime import date

from flask_wtf import FlaskForm
from wtforms import IntegerField, StringField, SubmitField
from wtforms.validators import DataRequired, Email, Length, Optional, Regexp, ValidationError


class StudentForm(FlaskForm):
    full_name = StringField(
        "Full Name",
        validators=[DataRequired(), Length(min=2, max=100)],
    )
    roll_number = StringField(
        "Roll Number",
        validators=[
            DataRequired(),
            Length(min=2, max=50),
            Regexp(r"^[A-Za-z0-9\-_/]+$", message="Roll number may only contain letters, digits, - _ /"),
        ],
    )
    course = StringField(
        "Course",
        validators=[DataRequired(), Length(min=2, max=100)],
    )
    year_of_passing = IntegerField(
        "Year of Passing",
        validators=[DataRequired()],
    )
    email = StringField(
        "Email",
        validators=[Optional(), Email(message="Enter a valid email address."), Length(max=100)],
    )
    phone = StringField(
        "Phone",
        validators=[Optional(), Regexp(r"^\+?[0-9\- ]{7,15}$", message="Enter a valid phone number.")],
    )
    submit = SubmitField("Save Student")

    def validate_year_of_passing(self, field):
        """Sanity-bound the year rather than accepting any integer
        (e.g. reject 1800 or 3000, which are almost certainly typos)."""
        current_year = date.today().year
        if field.data < 1980 or field.data > current_year + 6:
            raise ValidationError(
                f"Year of passing must be between 1980 and {current_year + 6}."
            )
