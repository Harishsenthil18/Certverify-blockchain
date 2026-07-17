"""
tests/test_certificates.py
----------------------------
Integration tests for certificate upload: hashing, duplicate prevention,
blockchain block creation, and atomic transaction rollback on failure.

TESTING NOTE: the blockchain repository (app/blockchain/repository.py)
writes MySQL-specific parameterized SQL ("%s" placeholders) directly via
a raw DB-API cursor, by design (see Phase 3) -- this is NOT compatible
with SQLite's "?" placeholder syntax used by the test database. So
these tests mock BlockchainRepository.save_block() (verifying it's
CALLED with the right arguments) rather than exercising a real SQL
INSERT against SQLite. The in-memory Blockchain class itself (add_block,
is_chain_valid, rollback_last_block) runs for real, unmocked -- only the
MySQL-specific persistence call is mocked.

CANNOT BE EXECUTED IN THIS SANDBOX -- see test_auth.py's docstring.
Run locally via: python -m unittest tests.test_certificates -v
"""

import io
import unittest
from unittest.mock import patch

from tests.helpers import login, make_test_app, seed_admin

MINIMAL_PDF_BYTES = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF"


def _add_student(client, roll_number="CS2022001"):
    return client.post(
        "/students/add",
        data={"full_name": "Ananya Sharma", "roll_number": roll_number,
              "course": "B.Tech CSE", "year_of_passing": "2026"},
        follow_redirects=True,
    )


def _upload_payload(student_id, pdf_bytes=MINIMAL_PDF_BYTES, filename="cert.pdf",
                     course_name="B.Tech Computer Science", grade="A+", issue_date="2026-01-01"):
    return {
        "student_id": str(student_id),
        "course_name": course_name,
        "grade": grade,
        "issue_date": issue_date,
        "certificate_file": (io.BytesIO(pdf_bytes), filename),
    }


class TestCertificateUpload(unittest.TestCase):

    def setUp(self):
        self.app = make_test_app()
        self.client = self.app.test_client()
        seed_admin(self.app, username="admin1", password="CorrectPass1!")
        login(self.client, "admin1", "CorrectPass1!")

        # Ensure the in-memory blockchain has a genesis block -- in this
        # sandboxed test environment there is no real MySQL server, so
        # create_app()'s startup blockchain load fails gracefully and
        # leaves an EMPTY chain (see app/__init__.py's _init_blockchain).
        with self.app.app_context():
            self.app.extensions["blockchain_chain"].create_genesis_block()

        _add_student(self.client)
        from app.students.models import Student
        with self.app.app_context():
            self.student_id = Student.query.filter_by(roll_number="CS2022001").first().id

    def _mock_save_block(self):
        """Patch BlockchainRepository.save_block to assign a fake db_id
        instead of executing real MySQL SQL against SQLite."""
        def fake_save_block(self_repo, block, cursor):
            block.db_id = block.index  # deterministic fake primary key
            return block.db_id
        return patch("app.certificates.routes.BlockchainRepository.save_block", fake_save_block)

    def _mock_write_cursor(self):
        """The route calls get_write_cursor_for_current_transaction() to
        obtain a cursor for the (mocked) repository call -- return a
        harmless dummy object since save_block is mocked anyway."""
        return patch("app.certificates.routes.get_write_cursor_for_current_transaction", return_value=object())

    def test_upload_certificate_success(self):
        with self._mock_save_block(), self._mock_write_cursor():
            response = self.client.post(
                "/certificates/upload",
                data=_upload_payload(self.student_id),
                content_type="multipart/form-data",
                follow_redirects=True,
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"recorded on the blockchain successfully", response.data)

        from app.certificates.models import Certificate
        with self.app.app_context():
            cert = Certificate.query.first()
            self.assertIsNotNone(cert)
            self.assertTrue(cert.certificate_id.startswith("CERT-"))
            self.assertEqual(len(cert.file_hash), 64)
            self.assertEqual(len(cert.combined_hash), 64)

        # The block should now be in the in-memory chain too.
        with self.app.app_context():
            chain = self.app.extensions["blockchain_chain"]
            self.assertEqual(len(chain), 2)  # genesis + 1 new block
            is_valid, reason = chain.is_chain_valid()
            self.assertTrue(is_valid, reason)

    def test_duplicate_certificate_rejected(self):
        with self._mock_save_block(), self._mock_write_cursor():
            self.client.post(
                "/certificates/upload", data=_upload_payload(self.student_id),
                content_type="multipart/form-data", follow_redirects=True,
            )
            # Re-upload the EXACT same student + course + grade + date + file.
            response = self.client.post(
                "/certificates/upload", data=_upload_payload(self.student_id),
                content_type="multipart/form-data", follow_redirects=True,
            )
        self.assertIn(b"already been uploaded", response.data)

        from app.certificates.models import Certificate
        with self.app.app_context():
            self.assertEqual(Certificate.query.count(), 1)  # second upload was rejected, not duplicated

    def test_same_student_different_file_is_not_a_duplicate(self):
        """Re-issuing a corrected PDF for the same course/grade/date must
        be ALLOWED -- only byte-identical files count as duplicates."""
        with self._mock_save_block(), self._mock_write_cursor():
            self.client.post(
                "/certificates/upload", data=_upload_payload(self.student_id),
                content_type="multipart/form-data", follow_redirects=True,
            )
            response = self.client.post(
                "/certificates/upload",
                data=_upload_payload(self.student_id, pdf_bytes=MINIMAL_PDF_BYTES + b"\nEXTRA"),
                content_type="multipart/form-data", follow_redirects=True,
            )
        self.assertIn(b"recorded on the blockchain successfully", response.data)

        from app.certificates.models import Certificate
        with self.app.app_context():
            self.assertEqual(Certificate.query.count(), 2)

    def test_upload_rejects_non_pdf_content(self):
        with self._mock_save_block(), self._mock_write_cursor():
            response = self.client.post(
                "/certificates/upload",
                data=_upload_payload(self.student_id, pdf_bytes=b"not a real pdf file"),
                content_type="multipart/form-data",
                follow_redirects=True,
            )
        # Flask-WTF's FileAllowed checks the extension client-side info,
        # but our own validate_pdf_content() checks real magic bytes --
        # renamed-but-fake files must still be rejected.
        self.assertIn(b"does not appear to be a valid PDF", response.data)

    def test_upload_rejects_future_issue_date(self):
        response = self.client.post(
            "/certificates/upload",
            data=_upload_payload(self.student_id, issue_date="2099-01-01"),
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        self.assertIn(b"cannot be in the future", response.data)

    def test_failed_transaction_rolls_back_in_memory_block(self):
        """If the DB commit fails AFTER add_block() ran, the in-memory
        chain must roll back too -- otherwise the next upload would link
        to a 'ghost' block that was never persisted."""
        with self.app.app_context():
            chain_len_before = len(self.app.extensions["blockchain_chain"])

        with self._mock_write_cursor():
            with patch(
                "app.certificates.routes.BlockchainRepository.save_block",
                side_effect=RuntimeError("simulated DB failure"),
            ):
                response = self.client.post(
                    "/certificates/upload", data=_upload_payload(self.student_id),
                    content_type="multipart/form-data", follow_redirects=True,
                )

        self.assertIn(b"unexpected error", response.data.lower())

        with self.app.app_context():
            chain_len_after = len(self.app.extensions["blockchain_chain"])
            self.assertEqual(
                chain_len_before, chain_len_after,
                "In-memory chain must be rolled back to its pre-upload length after a failed transaction.",
            )

        from app.certificates.models import Certificate
        with self.app.app_context():
            self.assertEqual(Certificate.query.count(), 0)

    def test_upload_requires_login(self):
        self.client.get("/auth/logout")
        response = self.client.get("/certificates/upload", follow_redirects=True)
        self.assertIn(b"Admin Login", response.data)


if __name__ == "__main__":
    unittest.main()
