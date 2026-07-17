"""
auth/forms.py
-------------
WTForms form definitions for admin authentication.
FlaskForm automatically wires in CSRF protection (a hidden csrf_token
field is rendered by the template and validated on submit).
"""

from flask_wtf import FlaskForm
from wtforms import BooleanField, PasswordField, StringField, SubmitField
from wtforms.validators import DataRequired, Length


class LoginForm(FlaskForm):
    username = StringField(
        "Username",
        validators=[DataRequired(message="Username is required."), Length(max=50)],
    )
    password = PasswordField(
        "Password",
        validators=[DataRequired(message="Password is required.")],
    )
    remember_me = BooleanField("Remember Me")
    submit = SubmitField("Login")
