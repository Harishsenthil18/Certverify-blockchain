"""
qr/generator.py
----------------
Generates a QR code image encoding a certificate's public verification
URL, so anyone (employer, university, etc.) can scan it and land
directly on the verification result for that certificate.
"""

import logging
import os

import qrcode

logger = logging.getLogger(__name__)


def generate_certificate_qr(certificate_id, verification_base_url, output_folder):
    """
    Generate and save a QR code PNG encoding the verification URL for a
    given certificate_id.

    Args:
        certificate_id (str): e.g. "CERT-2026-000001".
        verification_base_url (str): e.g. "http://localhost:5000/verify".
        output_folder (str): absolute path to the QR code storage folder.

    Returns:
        str: the filename (not full path) of the generated QR image,
            e.g. "CERT-2026-000001.png" -- callers store this in the
            certificates table or reconstruct the URL for display.

    Raises:
        OSError: if the file cannot be written (disk full, permissions, etc.)
            -- deliberately NOT swallowed here, so the caller (the upload
            route) can decide whether a QR failure should block the
            certificate upload or just be logged as a non-fatal warning.
    """
    verification_url = f"{verification_base_url.rstrip('/')}/{certificate_id}"

    qr = qrcode.QRCode(
        version=None,  # auto-size to fit the data
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=4,
    )
    qr.add_data(verification_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")

    os.makedirs(output_folder, exist_ok=True)
    filename = f"{certificate_id}.png"
    output_path = os.path.join(output_folder, filename)
    img.save(output_path)

    logger.info("QR code generated for %s -> %s", certificate_id, output_path)
    return filename
