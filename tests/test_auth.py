"""
tests/test_auth.py
-------------------
Integration tests for admin login/logout, using Flask's test client
against an in-memory SQLite-backed test app.

CANNOT BE EXECUTED IN THIS SANDBOX (no network to install Flask-Login /
Flask-SQLAlchemy / Flask-WTF / PyMySQL). Run locally after
`pip install -r requirements.txt` via:
    python -m unittest tests.test_auth -v
"""

import unittest

from tests.helpers import login, make_test_app, seed_admin


class TestLogin(unittest.TestCase):

    def setUp(self):
        self.app = make_test_app()
        self.client = self.app.test_client()
        seed_admin(self.app, username="admin1", password="CorrectPass1!")

    def test_login_page_loads(self):
        response = self.client.get("/auth/login")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Admin Login", response.data)

    def test_login_with_correct_credentials_succeeds(self):
        response = login(self.client, "admin1", "CorrectPass1!")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Dashboard", response.data)

    def test_login_with_wrong_password_fails(self):
        response = login(self.client, "admin1", "WrongPassword")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Invalid username or password", response.data)

    def test_login_with_nonexistent_username_fails_with_same_message(self):
        """The error message must be identical to the wrong-password case
        -- this is a deliberate anti-username-enumeration measure."""
        response = login(self.client, "no_such_user", "whatever")
        self.assertIn(b"Invalid username or password", response.data)

    def test_protected_page_redirects_anonymous_user_to_login(self):
        response = self.client.get("/students/dashboard", follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Admin Login", response.data)

    def test_logout_clears_session(self):
        login(self.client, "admin1", "CorrectPass1!")
        response = self.client.get("/auth/logout", follow_redirects=True)
        self.assertIn(b"logged out", response.data.lower())

        # After logout, the dashboard should redirect to login again.
        response2 = self.client.get("/students/dashboard", follow_redirects=True)
        self.assertIn(b"Admin Login", response2.data)

    def test_deactivated_admin_cannot_login(self):
        from app.auth.models import Admin
        from app.extensions import db

        with self.app.app_context():
            admin = Admin.query.filter_by(username="admin1").first()
            admin.is_active_flag = False
            db.session.commit()

        response = login(self.client, "admin1", "CorrectPass1!")
        self.assertIn(b"deactivated", response.data.lower())


class TestAdminPasswordHashing(unittest.TestCase):
    """Unit-level tests for the Admin model's password handling, not
    requiring the test client."""

    def setUp(self):
        self.app = make_test_app()

    def test_password_is_never_stored_in_plaintext(self):
        from app.auth.models import Admin

        with self.app.app_context():
            admin = Admin(username="x", full_name="X")
            admin.set_password("MySecretPassword123")
            self.assertNotEqual(admin.password_hash, "MySecretPassword123")
            self.assertTrue(admin.password_hash.startswith("pbkdf2:sha256:"))

    def test_check_password_correct_and_incorrect(self):
        from app.auth.models import Admin

        with self.app.app_context():
            admin = Admin(username="x", full_name="X")
            admin.set_password("CorrectHorseBatteryStaple")
            self.assertTrue(admin.check_password("CorrectHorseBatteryStaple"))
            self.assertFalse(admin.check_password("WrongPassword"))


if __name__ == "__main__":
    unittest.main()
