"""
tests/test_students.py
------------------------
Integration tests for student CRUD routes. Cannot be executed in this
sandbox -- see test_auth.py's module docstring for why. Run locally via:
    python -m unittest tests.test_students -v
"""

import unittest

from tests.helpers import login, make_test_app, seed_admin


class TestStudentCRUD(unittest.TestCase):

    def setUp(self):
        self.app = make_test_app()
        self.client = self.app.test_client()
        seed_admin(self.app, username="admin1", password="CorrectPass1!")
        login(self.client, "admin1", "CorrectPass1!")

    def test_add_student_success(self):
        response = self.client.post(
            "/students/add",
            data={
                "full_name": "Ananya Sharma",
                "roll_number": "CS2022001",
                "course": "B.Tech CSE",
                "year_of_passing": "2026",
                "email": "ananya@example.com",
                "phone": "9876543210",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"added successfully", response.data)
        self.assertIn(b"Ananya Sharma", response.data)

    def test_add_student_duplicate_roll_number_rejected(self):
        payload = {
            "full_name": "Student One",
            "roll_number": "CS2022099",
            "course": "B.Tech CSE",
            "year_of_passing": "2026",
        }
        self.client.post("/students/add", data=payload, follow_redirects=True)
        response = self.client.post(
            "/students/add",
            data={**payload, "full_name": "Student Two"},
            follow_redirects=True,
        )
        self.assertIn(b"already exists", response.data)

    def test_add_student_invalid_year_rejected(self):
        response = self.client.post(
            "/students/add",
            data={
                "full_name": "Bad Year Student",
                "roll_number": "CS2022123",
                "course": "B.Tech CSE",
                "year_of_passing": "1800",
            },
            follow_redirects=True,
        )
        self.assertIn(b"Year of passing must be between", response.data)

    def test_add_student_missing_required_field_rejected(self):
        response = self.client.post(
            "/students/add",
            data={"full_name": "", "roll_number": "CS9999", "course": "X", "year_of_passing": "2026"},
            follow_redirects=True,
        )
        # Should re-render the form with a validation error, not redirect.
        self.assertIn(b"This field is required", response.data)

    def test_list_students_shows_added_student(self):
        self.client.post(
            "/students/add",
            data={"full_name": "Rohit Verma", "roll_number": "CS2022050",
                  "course": "B.Tech CSE", "year_of_passing": "2026"},
            follow_redirects=True,
        )
        response = self.client.get("/students/")
        self.assertIn(b"Rohit Verma", response.data)

    def test_search_students_filters_results(self):
        self.client.post(
            "/students/add",
            data={"full_name": "Priya Natarajan", "roll_number": "EC2022015",
                  "course": "B.Tech ECE", "year_of_passing": "2026"},
            follow_redirects=True,
        )
        self.client.post(
            "/students/add",
            data={"full_name": "Karthik Iyer", "roll_number": "ME2021034",
                  "course": "B.Tech ME", "year_of_passing": "2025"},
            follow_redirects=True,
        )
        response = self.client.get("/students/?q=Priya")
        self.assertIn(b"Priya Natarajan", response.data)
        self.assertNotIn(b"Karthik Iyer", response.data)

    def test_edit_student_updates_fields(self):
        self.client.post(
            "/students/add",
            data={"full_name": "Original Name", "roll_number": "CS2022077",
                  "course": "B.Tech CSE", "year_of_passing": "2026"},
            follow_redirects=True,
        )
        from app.students.models import Student
        with self.app.app_context():
            student_id = Student.query.filter_by(roll_number="CS2022077").first().id

        response = self.client.post(
            f"/students/{student_id}/edit",
            data={"full_name": "Updated Name", "roll_number": "CS2022077",
                  "course": "B.Tech CSE", "year_of_passing": "2026"},
            follow_redirects=True,
        )
        self.assertIn(b"updated successfully", response.data)
        self.assertIn(b"Updated Name", response.data)

    def test_delete_student_without_certificates_succeeds(self):
        self.client.post(
            "/students/add",
            data={"full_name": "To Delete", "roll_number": "CS2022088",
                  "course": "B.Tech CSE", "year_of_passing": "2026"},
            follow_redirects=True,
        )
        from app.students.models import Student
        with self.app.app_context():
            student_id = Student.query.filter_by(roll_number="CS2022088").first().id

        response = self.client.post(f"/students/{student_id}/delete", follow_redirects=True)
        self.assertIn(b"Student deleted", response.data)

        response2 = self.client.get("/students/")
        self.assertNotIn(b"To Delete", response2.data)

    def test_delete_student_with_certificates_is_blocked(self):
        """A student who has an issued certificate must not be deletable
        -- mirrors the DB-level ON DELETE RESTRICT."""
        from app.certificates.models import Certificate
        from app.students.models import Student
        from app.extensions import db
        from datetime import date

        self.client.post(
            "/students/add",
            data={"full_name": "Has Certificate", "roll_number": "CS2022200",
                  "course": "B.Tech CSE", "year_of_passing": "2026"},
            follow_redirects=True,
        )
        with self.app.app_context():
            student = Student.query.filter_by(roll_number="CS2022200").first()
            cert = Certificate(
                certificate_id="CERT-2026-000999",
                student_id=student.id,
                course_name="B.Tech CSE",
                grade="A",
                issue_date=date(2026, 1, 1),
                file_path="dummy.pdf",
                original_filename="dummy.pdf",
                file_hash="a" * 64,
                data_hash="b" * 64,
                combined_hash="c" * 64,
                block_id=1,
            )
            db.session.add(cert)
            db.session.commit()
            student_id = student.id

        response = self.client.post(f"/students/{student_id}/delete", follow_redirects=True)
        self.assertIn(b"Cannot delete", response.data)

    def test_students_route_requires_login(self):
        self.client.get("/auth/logout")
        response = self.client.get("/students/", follow_redirects=True)
        self.assertIn(b"Admin Login", response.data)


if __name__ == "__main__":
    unittest.main()
