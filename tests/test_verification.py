"""
tests/test_verification.py
-----------------------------
Integration tests for the verification routes: by Certificate ID and by
uploaded PDF, covering all three results (VALID, TAMPERED, NOT_FOUND).

CANNOT BE EXECUTED IN THIS SANDBOX -- see test_auth.py's docstring.
Run locally via: python -m unittest tests.test_verification -v
"""

import io
import unittest
from unittest.mock import patch

from tests.helpers import login, make_test_app, seed_admin
from tests.test_certificates import MINIMAL_PDF_BYTES, _add_student, _upload_payload


class TestVerification(unittest.TestCase):

    def setUp(self):
        self.app = make_test_app()
        self.client = self.app.test_client()
        seed_admin(self.app, username="admin1", password="CorrectPass1!")
        login(self.client, "admin1", "CorrectPass1!")

        with self.app.app_context():
            self.app.extensions["blockchain_chain"].create_genesis_block()

        _add_student(self.client)
        from app.students.models import Student
        with self.app.app_context():
            self.student_id = Student.query.filter_by(roll_number="CS2022001").first().id

        with patch("app.certificates.routes.BlockchainRepository.save_block",
                   lambda self_repo, block, cursor: setattr(block, "db_id", block.index) or block.index), \
             patch("app.certificates.routes.get_write_cursor_for_current_transaction", return_value=object()):
            self.client.post(
                "/certificates/upload", data=_upload_payload(self.student_id),
                content_type="multipart/form-data", follow_redirects=True,
            )

        from app.certificates.models import Certificate
        with self.app.app_context():
            self.certificate = Certificate.query.first()
            self.certificate_id = self.certificate.certificate_id

        # Verification routes are public -- log out so tests reflect a
        # real anonymous visitor.
        self.client.get("/auth/logout")

    def test_verify_by_id_valid_certificate(self):
        response = self.client.post(
            "/verify/by-id", data={"certificate_id": self.certificate_id}, follow_redirects=True,
        )
        self.assertIn(b"Valid Certificate", response.data)

    def test_verify_by_id_not_found(self):
        response = self.client.post(
            "/verify/by-id", data={"certificate_id": "CERT-2026-999999"}, follow_redirects=True,
        )
        self.assertIn(b"Certificate Not Found", response.data)

    def test_verify_by_id_invalid_format_rejected_by_form(self):
        response = self.client.post(
            "/verify/by-id", data={"certificate_id": "not-a-valid-id"}, follow_redirects=True,
        )
        self.assertIn(b"Format must be", response.data)

    def test_verify_direct_link_from_qr_code(self):
        """The URL embedded in a certificate's QR code (/verify/<id>)
        must work as a direct GET, not just via the form POST."""
        response = self.client.get(f"/verify/{self.certificate_id}")
        self.assertIn(b"Valid Certificate", response.data)

    def test_verify_detects_tampered_certificate_data(self):
        """Simulate an attacker directly editing the certificate's grade
        in the database -- verification must report TAMPERED, not VALID,
        because the recomputed data_hash will no longer match."""
        from app.certificates.models import Certificate
        from app.extensions import db

        with self.app.app_context():
            cert = Certificate.query.filter_by(certificate_id=self.certificate_id).first()
            cert.grade = "F"  # tamper: attacker "upgrades" or alters the grade directly in DB
            db.session.commit()

        response = self.client.post(
            "/verify/by-id", data={"certificate_id": self.certificate_id}, follow_redirects=True,
        )
        self.assertIn(b"Tampered Certificate", response.data)

    def test_verify_detects_tampered_blockchain_block(self):
        """Simulate an attacker directly editing the blockchain block's
        certificate_hash in memory (standing in for a direct DB edit to
        blockchain_blocks) -- must report TAMPERED."""
        with self.app.app_context():
            chain = self.app.extensions["blockchain_chain"]
            block = chain.find_block_by_certificate_hash(self.certificate.combined_hash)
            self.assertIsNotNone(block)
            block.current_hash = "f" * 64  # tamper the block's own hash directly

        response = self.client.post(
            "/verify/by-id", data={"certificate_id": self.certificate_id}, follow_redirects=True,
        )
        self.assertIn(b"Tampered Certificate", response.data)

    def test_verify_by_file_valid_unmodified_file(self):
        response = self.client.post(
            "/verify/by-file",
            data={"certificate_file": (io.BytesIO(MINIMAL_PDF_BYTES), "cert.pdf")},
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        self.assertIn(b"Valid Certificate", response.data)

    def test_verify_by_file_unrelated_file_not_found(self):
        unrelated_pdf = b"%PDF-1.4\nunrelated content that was never uploaded\n%%EOF"
        response = self.client.post(
            "/verify/by-file",
            data={"certificate_file": (io.BytesIO(unrelated_pdf), "random.pdf")},
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        self.assertIn(b"Certificate Not Found", response.data)

    def test_verify_by_file_rejects_non_pdf(self):
        response = self.client.post(
            "/verify/by-file",
            data={"certificate_file": (io.BytesIO(b"just some text"), "fake.pdf")},
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        self.assertIn(b"does not appear to be a valid PDF", response.data)

    def test_verification_attempt_is_logged(self):
        from app.verification.models import VerificationLog

        self.client.post("/verify/by-id", data={"certificate_id": self.certificate_id}, follow_redirects=True)

        with self.app.app_context():
            log = VerificationLog.query.filter_by(certificate_id=self.certificate_id).first()
            self.assertIsNotNone(log)
            self.assertEqual(log.result, "VALID")
            self.assertEqual(log.verification_method, "ID")

    def test_verification_page_does_not_require_login(self):
        """The whole point of verification is that anonymous third
        parties can use it -- confirm no login redirect happens."""
        response = self.client.get("/verify/")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"Admin Login", response.data)


if __name__ == "__main__":
    unittest.main()
