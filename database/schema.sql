-- =====================================================================
-- Academic Certificate Verification System
-- Database Schema (MySQL 8.0+)
-- =====================================================================
-- Design notes:
--   - Engine = InnoDB everywhere (required for FOREIGN KEY support and
--     transactional integrity when we insert a certificate + a block
--     together).
--   - Charset = utf8mb4 (supports full Unicode incl. student names in
--     regional scripts, emojis in free-text fields, etc.)
--   - Table creation order matters because of FK dependencies:
--       admins, students, blockchain_blocks  -> no dependencies
--       certificates                          -> depends on students,
--                                                 blockchain_blocks
--       certificate_sequence                  -> no dependencies
--       verification_logs                     -> no FK (intentionally
--                                                 loose, explained below)
-- =====================================================================

-- Create and use a dedicated database
CREATE DATABASE IF NOT EXISTS certverify_db
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE certverify_db;

-- Safety: drop tables in reverse dependency order if re-running script
-- during development. (Comment this block out in production!)
-- DROP TABLE IF EXISTS verification_logs;
-- DROP TABLE IF EXISTS certificates;
-- DROP TABLE IF EXISTS certificate_sequence;
-- DROP TABLE IF EXISTS blockchain_blocks;
-- DROP TABLE IF EXISTS students;
-- DROP TABLE IF EXISTS admins;

-- =====================================================================
-- TABLE: admins
-- Stores admin login credentials. Passwords are NEVER stored in
-- plaintext -- password_hash holds a Werkzeug PBKDF2-SHA256 hash.
-- =====================================================================
CREATE TABLE IF NOT EXISTS admins (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    username        VARCHAR(50)  NOT NULL,
    password_hash   VARCHAR(255) NOT NULL,   -- Werkzeug hash, ~100 chars, 255 gives headroom
    full_name       VARCHAR(100) NOT NULL,
    is_active       TINYINT(1)   NOT NULL DEFAULT 1,
    created_at      TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_login_at   TIMESTAMP    NULL DEFAULT NULL,

    CONSTRAINT uq_admins_username UNIQUE (username)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- =====================================================================
-- TABLE: students
-- Stores basic student records that certificates are issued against.
-- =====================================================================
CREATE TABLE IF NOT EXISTS students (
    id                INT AUTO_INCREMENT PRIMARY KEY,
    full_name         VARCHAR(100) NOT NULL,
    roll_number       VARCHAR(50)  NOT NULL,
    course            VARCHAR(100) NOT NULL,
    year_of_passing   YEAR         NOT NULL,
    email             VARCHAR(100) NULL,
    phone             VARCHAR(15)  NULL,
    created_at        TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at        TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP
                                    ON UPDATE CURRENT_TIMESTAMP,

    CONSTRAINT uq_students_roll_number UNIQUE (roll_number)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Index to speed up name-based admin searches ("find student by name")
CREATE INDEX idx_students_full_name ON students (full_name);


-- =====================================================================
-- TABLE: blockchain_blocks
-- Each row = one block in our custom blockchain.
-- block_index = 0 is the Genesis Block, inserted once at DB init time.
-- =====================================================================
CREATE TABLE IF NOT EXISTS blockchain_blocks (
    id                 INT AUTO_INCREMENT PRIMARY KEY,
    block_index        INT       NOT NULL,
    block_timestamp    DATETIME(6) NOT NULL,   -- microsecond precision to avoid
                                                -- identical timestamps in fast test runs
    certificate_hash   CHAR(64)  NOT NULL,     -- SHA-256 hex digest (64 hex chars)
    previous_hash      CHAR(64)  NOT NULL,
    current_hash       CHAR(64)  NOT NULL,
    created_at         TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT uq_blocks_index UNIQUE (block_index),
    CONSTRAINT uq_blocks_current_hash UNIQUE (current_hash)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Index for fast "get latest block" queries (ORDER BY block_index DESC LIMIT 1)
CREATE INDEX idx_blocks_index ON blockchain_blocks (block_index);
-- Index for fast lookup by hash during chain validation walks
CREATE INDEX idx_blocks_current_hash ON blockchain_blocks (current_hash);


-- =====================================================================
-- TABLE: certificate_sequence
-- Helper table to safely generate human-readable Certificate IDs like
-- CERT-2026-000001 without race conditions under concurrent inserts.
-- One row per calendar year; last_serial increments per new certificate.
-- We rely on a transactional UPDATE ... SELECT FOR UPDATE pattern in the
-- application layer (Phase 4) to avoid two admins getting the same number.
-- =====================================================================
CREATE TABLE IF NOT EXISTS certificate_sequence (
    year          INT PRIMARY KEY,
    last_serial   INT NOT NULL DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- =====================================================================
-- TABLE: certificates
-- Core table linking a student, an uploaded PDF, its hashes, and the
-- blockchain block that immutably records it.
-- =====================================================================
CREATE TABLE IF NOT EXISTS certificates (
    id                INT AUTO_INCREMENT PRIMARY KEY,
    certificate_id    VARCHAR(20)  NOT NULL,   -- e.g. CERT-2026-000001
    student_id        INT          NOT NULL,
    course_name       VARCHAR(150) NOT NULL,
    grade             VARCHAR(20)  NOT NULL,
    issue_date        DATE         NOT NULL,
    file_path         VARCHAR(255) NOT NULL,   -- relative path on disk, e.g. uploads/certificates/<hash>.pdf
    original_filename VARCHAR(255) NOT NULL,   -- original name as uploaded, kept for display only
    file_hash         CHAR(64)     NOT NULL,   -- SHA-256 of raw PDF bytes
    data_hash         CHAR(64)     NOT NULL,   -- SHA-256 of certificate metadata string
    combined_hash     CHAR(64)     NOT NULL,   -- SHA-256(data_hash + file_hash) -> duplicate guard
    block_id          INT          NOT NULL,   -- FK -> blockchain_blocks.id
    uploaded_by       INT          NULL,       -- FK -> admins.id (who issued it)
    created_at        TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT uq_certificates_certificate_id UNIQUE (certificate_id),
    CONSTRAINT uq_certificates_combined_hash  UNIQUE (combined_hash),
    CONSTRAINT uq_certificates_block_id       UNIQUE (block_id),

    CONSTRAINT fk_certificates_student
        FOREIGN KEY (student_id) REFERENCES students(id)
        ON DELETE RESTRICT   -- prevent deleting a student who has certificates
        ON UPDATE CASCADE,

    CONSTRAINT fk_certificates_block
        FOREIGN KEY (block_id) REFERENCES blockchain_blocks(id)
        ON DELETE RESTRICT   -- a certificate must never outlive its block record
        ON UPDATE CASCADE,

    CONSTRAINT fk_certificates_admin
        FOREIGN KEY (uploaded_by) REFERENCES admins(id)
        ON DELETE SET NULL   -- if admin account is removed, keep the certificate
        ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Index for the two verification lookup paths:
CREATE INDEX idx_certificates_file_hash ON certificates (file_hash);
CREATE INDEX idx_certificates_student_id ON certificates (student_id);
-- (certificate_id and combined_hash already indexed via UNIQUE constraints)


-- =====================================================================
-- TABLE: verification_logs
-- Records every verification attempt (successful or not), for audit
-- history. Intentionally has NO foreign key to certificates: a
-- verification attempt for a certificate_id that does NOT exist must
-- still be logged (NOT_FOUND case), and enforcing an FK would make that
-- impossible unless we made it nullable + ON DELETE SET NULL -- but since
-- we're logging the *string* the user typed (which might be garbage or
-- a typo), a loose text column + index is the correct, simpler design.
-- =====================================================================
CREATE TABLE IF NOT EXISTS verification_logs (
    id                     BIGINT AUTO_INCREMENT PRIMARY KEY,
    certificate_id         VARCHAR(20) NULL,        -- as typed / resolved; NULL if PDF match failed entirely
    verification_method    ENUM('ID', 'FILE')       NOT NULL,
    result                 ENUM('VALID', 'TAMPERED', 'NOT_FOUND') NOT NULL,
    ip_address             VARCHAR(45) NULL,         -- IPv4 or IPv6
    user_agent             VARCHAR(255) NULL,
    verified_at            TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Index for admin dashboard queries like "show all logs for this certificate"
CREATE INDEX idx_logs_certificate_id ON verification_logs (certificate_id);
-- Index for time-based queries ("today's verification attempts")
CREATE INDEX idx_logs_verified_at ON verification_logs (verified_at);
-- Index for filtering by result (e.g. count all TAMPERED attempts)
CREATE INDEX idx_logs_result ON verification_logs (result);


-- =====================================================================
-- SEED DATA: Default Admin Account
-- Username: admin
-- Password: Admin@123   (CHANGE THIS after first login in a real deployment)
-- Hash generated using Werkzeug's generate_password_hash()
-- (method='pbkdf2:sha256', salted) -- verified working hash, not a placeholder.
-- =====================================================================
INSERT INTO admins (username, password_hash, full_name, is_active)
VALUES (
    'admin',
    'pbkdf2:sha256:1000000$hAFBaTx9u0HUOH0E$f25da783abc52e7ba1206cbb7f9b6a109cff90738bb013edbcbcc312a834dd39',
    'System Administrator',
    1
);


-- =====================================================================
-- GENESIS BLOCK INSERTION
-- Every blockchain needs a starting block with no real predecessor.
-- Convention: previous_hash = 64 zeros ("0"*64), certificate_hash =
-- 64 zeros too (no real certificate attached to genesis).
-- current_hash is computed the SAME way the app computes it for every
-- other block: SHA256(index + timestamp + certificate_hash + previous_hash)
-- Below, the timestamp used is fixed at DB-init time so the hash is
-- reproducible; the app's Blockchain class will load this exact row
-- and treat it as block_index = 0 going forward.
-- =====================================================================
INSERT INTO blockchain_blocks (
    block_index,
    block_timestamp,
    certificate_hash,
    previous_hash,
    current_hash
)
VALUES (
    0,
    '2026-01-01 00:00:00.000000',
    '0000000000000000000000000000000000000000000000000000000000000000',
    '0000000000000000000000000000000000000000000000000000000000000000',
    -- current_hash = SHA256("0" + "2026-01-01 00:00:00.000000" + certificate_hash + previous_hash)
    -- Computed with Python's hashlib.sha256() using the EXACT concatenation
    -- formula that Block.compute_hash() implements in Phase 3, so this row
    -- will pass chain validation the first time the app loads it. Verified
    -- reproducible, not a placeholder.
    '0352a0f4aa338a25b3957d69ec7eb396b86800d9eafaf8a732af82d77f5aae04'
);

-- Initialize the certificate_sequence row for the current year.
-- Phase 4's ID-generation logic will INSERT ... ON DUPLICATE KEY UPDATE
-- new years automatically, so this seed is just a starting convenience.
INSERT INTO certificate_sequence (year, last_serial)
VALUES (2026, 0)
ON DUPLICATE KEY UPDATE last_serial = last_serial;
