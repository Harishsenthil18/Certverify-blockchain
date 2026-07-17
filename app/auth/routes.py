"""
auth/routes.py
---------------
Admin login/logout routes. Session management itself (cookies, "remember
me", login_required enforcement) is handled by Flask-Login, configured
in app/__init__.py; this module only implements the actual login/logout
view functions.
"""

import logging

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from app.auth.forms import LoginForm
from app.auth.models import Admin
from app.extensions import db

logger = logging.getLogger(__name__)

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """Admin login. Deliberately gives the SAME error message whether
    the username doesn't exist or the password is wrong -- this avoids
    leaking which usernames are valid (a classic username-enumeration
    information leak)."""
    if current_user.is_authenticated:
        return redirect(url_for("students.dashboard"))

    form = LoginForm()
    if form.validate_on_submit():
        admin = Admin.query.filter_by(username=form.username.data.strip()).first()

        if admin is None or not admin.check_password(form.password.data):
            logger.warning("Failed login attempt for username=%r from ip=%s",
                            form.username.data, request.remote_addr)
            flash("Invalid username or password.", "danger")
            return render_template("auth/login.html", form=form)

        if not admin.is_active:
            logger.warning("Login attempt on deactivated account username=%r", admin.username)
            flash("This account has been deactivated. Contact the system administrator.", "danger")
            return render_template("auth/login.html", form=form)

        login_user(admin, remember=form.remember_me.data)

        from datetime import datetime
        admin.last_login_at = datetime.utcnow()
        db.session.commit()

        logger.info("Admin login successful: username=%r ip=%s", admin.username, request.remote_addr)
        flash(f"Welcome back, {admin.full_name}!", "success")

        # Respect Flask-Login's "next" redirect target (set by
        # @login_required when an anonymous user tries a protected page),
        # but ONLY if it's a safe, local, relative path -- never blindly
        # redirect to an attacker-supplied external URL (open-redirect
        # prevention).
        next_page = request.args.get("next")
        if next_page and next_page.startswith("/") and not next_page.startswith("//"):
            return redirect(next_page)
        return redirect(url_for("students.dashboard"))

    return render_template("auth/login.html", form=form)


@auth_bp.route("/logout")
@login_required
def logout():
    username = current_user.username
    logout_user()
    logger.info("Admin logout: username=%r", username)
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))
