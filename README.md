# Academic Certificate Verification and Validation Using Blockchain

A college mini-project that issues and verifies academic certificates using
SHA-256 hashing and a custom, tamper-evident blockchain implemented in pure
Python — no Ethereum, no mining, no Proof-of-Work, no cryptocurrency.

## Features

- Admin login/logout with hashed passwords (Werkzeug PBKDF2-SHA256), CSRF protection, session management
- Student management (add / edit / delete / search)
- Certificate upload: validates PDF type & size, computes SHA-256 hashes, prevents duplicate uploads
- Every certificate is recorded as a block in a custom Python blockchain (index, timestamp, certificate_hash, previous_hash, current_hash)
- Verification by Certificate ID **or** by re-uploading the PDF, returning Valid / Tampered / Not Found
- QR code generated per certificate, linking straight to its verification result
- Full verification history logged (method, result, IP, timestamp)
- Blockchain is loaded from MySQL and validated on every application startup

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | HTML5, CSS3, Bootstrap 5, vanilla JS |
| Backend | Python 3.11+, Flask, Flask-SQLAlchemy, Flask-Login, Flask-WTF |
| Database | MySQL 8.0+ |
| Security | SHA-256, Werkzeug password hashing, CSRF protection |
| Blockchain | Custom implementation (`app/blockchain/`) — no third-party blockchain library |
| QR Codes | `qrcode` + Pillow |

## Project Structure

```
certificate-verification-system/
├── app/
│   ├── auth/                # Login/logout blueprint
│   ├── students/             # Student CRUD blueprint + dashboard
│   ├── certificates/         # Upload, validators, ID generator
│   ├── verification/         # Verify by ID / by file
│   ├── blockchain/           # Block, Blockchain, Repository (zero Flask deps)
│   ├── qr/                   # QR code generator
│   ├── utils/                # Hashing, logging, PDF text extraction
│   ├── templates/            # Jinja2 templates (Bootstrap 5)
│   ├── static/                # CSS, JS, generated QR codes
│   ├── uploads/certificates/ # Stored certificate PDFs
│   ├── config.py
│   ├── extensions.py
│   └── __init__.py           # Application factory
├── database/
│   ├── schema.sql
│   ├── seed_data.sql
│   ├── test_queries.sql
│   ├── SETUP_INSTRUCTIONS.md
│   └── COMMON_ERRORS.md
├── tests/
├── logs/
├── .vscode/
├── requirements.txt
├── .env.example
├── run.py
└── README.md
```

## 1. Prerequisites

- Python 3.11+
- MySQL 8.0+
- Git (optional)

## 2. Setup

```bash
# Clone or unzip the project, then from the project root:
python -m venv venv

# Activate the virtual environment
source venv/bin/activate        # macOS/Linux
venv\Scripts\activate           # Windows

pip install -r requirements.txt
```

### Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` and set a real `SECRET_KEY`:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Paste the output as `SECRET_KEY=` in `.env`. Fill in your MySQL credentials
(see `database/SETUP_INSTRUCTIONS.md` for creating the restricted
`certverify_app` MySQL user — do NOT use `root` in `.env`).

### Initialize the database

```bash
mysql -u root -p < database/schema.sql
mysql -u root -p < database/seed_data.sql   # optional demo data
```

This creates all tables, the Genesis Block, and a default admin account:

```
Username: admin
Password: Admin@123
```

**Change this password after first login in any real deployment.**

## 3. Run the Application

```bash
python run.py
```

Visit `http://127.0.0.1:5000`. Admin routes are under `/auth/login`; the
public verification page is the homepage for anonymous visitors.

Alternatively, using the Flask CLI:

```bash
export FLASK_APP=run.py            # Windows: set FLASK_APP=run.py
export FLASK_ENV=development
flask run
```

## 4. Run Tests

```bash
python -m unittest discover -s tests -v
```

The blockchain module (`app/blockchain/*`) has zero Flask/DB dependencies
and its test suite (`test_block.py`, `test_blockchain.py`,
`test_repository.py`) runs standalone. Route-level integration tests
(`test_auth.py`, `test_students.py`, `test_certificates.py`,
`test_verification.py`) use an in-memory SQLite database via
`tests/helpers.py` and require the full `requirements.txt` to be installed.

## 5. VS Code

Open the project folder in VS Code. `.vscode/` already includes:
- `launch.json` — F5 to run/debug the app or the test suite
- `tasks.json` — Terminal > Run Task for venv setup, DB init, running the app, running tests
- `settings.json` — Python interpreter path, Jinja/HTML formatting
- `extensions.json` — recommended extensions (Python, Jinja, SQLTools)

## 6. Deployment Guide (production)

1. Set `FLASK_ENV=production` and a strong, unique `SECRET_KEY` in your
   production `.env`. Set `SESSION_COOKIE_SECURE=true` once served over HTTPS.
2. Use a real WSGI server instead of `run.py`'s dev server:
   ```bash
   gunicorn -w 4 -b 0.0.0.0:8000 "app:create_app()"
   ```
3. Put Nginx (or similar) in front of gunicorn as a reverse proxy, terminating TLS.
4. Point `VERIFICATION_BASE_URL` in `.env` at your real public domain so QR
   codes generated in production link correctly.
5. Ensure the MySQL user (`certverify_app`) only has `SELECT, INSERT, UPDATE,
   DELETE` — never `DROP`/`ALTER`/`CREATE` — on `certverify_db` (see
   `database/SETUP_INSTRUCTIONS.md`).
6. Back up `app/uploads/certificates/`, `app/static/qrcodes/`, and the MySQL
   database together — they represent one logical unit of data.
7. For simple free/low-cost hosting during a demo (e.g. a college
   evaluation), a small VPS (DigitalOcean/Linode droplet) or a PaaS with
   MySQL support (Render, Railway) both work; just repeat steps 1–4 there.

## 7. Debugging Guide

Start with `database/COMMON_ERRORS.md` (MySQL-side issues: FK errors,
strict-mode hash-length errors, connection errors). Additional Flask-level
issues:

| Symptom | Likely Cause | Fix |
|---|---|---|
| `RuntimeError: SECRET_KEY environment variable is not set` | `.env` missing or not loaded | `cp .env.example .env` and fill in `SECRET_KEY` |
| App starts but every certificate looks "Tampered" on first run | `blockchain_blocks` table is empty (schema.sql not run) | `mysql -u root -p < database/schema.sql` |
| `ModuleNotFoundError: No module named 'X'` | Virtual env not activated, or deps not installed | Activate `venv`, re-run `pip install -r requirements.txt` |
| Certificate upload succeeds but blockchain shows nothing new | The app connected to MySQL only for read access at startup, but the write path failed silently | Check `logs/app.log` for `Failed to save block` entries |
| CSRF token errors on form submit | `.env`'s `SECRET_KEY` changed between requests (e.g. server restarted mid-session) | Log in again after any server restart |
| QR code image missing on certificate detail page | QR generation failed post-upload (logged as a warning, non-fatal) | Check `logs/app.log`; certificate itself is still valid |

Application logs are in `logs/app.log` (rotated at 2MB, 5 backups kept).

## 8. Known Limitation

"Verify by uploaded PDF" identifies a certificate primarily via a
Certificate ID printed as text in the PDF. Since this system does not
currently stamp the assigned Certificate ID onto the PDF at upload time, a
byte-tampered PDF without any other identifying text may be reported as
"Not Found" rather than "Tampered." Verifying by Certificate ID (or by an
unmodified original file) is fully reliable. See the Future Enhancements
section of the project report for the planned fix (embedding the
Certificate ID + QR code onto the stored PDF at upload time).
