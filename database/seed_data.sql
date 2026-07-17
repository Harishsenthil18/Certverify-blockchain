-- =====================================================================
-- OPTIONAL: Sample seed data for demo/testing purposes
-- Run this AFTER schema.sql. Adds a few students so Phase 4/5 demos
-- have real data to work with (adding certificates requires the Flask
-- app since certificate rows need matching blockchain blocks --
-- we do NOT hand-insert certificates here to avoid an inconsistent
-- chain state).
-- =====================================================================

USE certverify_db;

INSERT INTO students (full_name, roll_number, course, year_of_passing, email, phone)
VALUES
    ('Ananya Sharma',   'CS2022001', 'B.Tech Computer Science', 2026, 'ananya.sharma@example.com', '9876543210'),
    ('Rohit Verma',     'CS2022002', 'B.Tech Computer Science', 2026, 'rohit.verma@example.com',   '9876543211'),
    ('Priya Natarajan', 'EC2022015', 'B.Tech Electronics',      2026, 'priya.n@example.com',       '9876543212'),
    ('Karthik Iyer',    'ME2021034', 'B.Tech Mechanical',       2025, 'karthik.iyer@example.com',  '9876543213'),
    ('Sneha Reddy',     'CS2022047', 'B.Tech Computer Science', 2026, 'sneha.reddy@example.com',   '9876543214')
ON DUPLICATE KEY UPDATE full_name = VALUES(full_name);   -- safe to re-run script

-- A second admin account for demonstrating multi-admin scenarios
-- Username: registrar   Password: Registrar@123
INSERT INTO admins (username, password_hash, full_name, is_active)
VALUES (
    'registrar',
    'pbkdf2:sha256:1000000$OFgUSqP7MhxXlkgY$cc21a6dd51c03f3787dd1dfa7cef60d87e14d8f7090cc160294594ce16639b84',
    'Registrar Office',
    1
)
ON DUPLICATE KEY UPDATE full_name = VALUES(full_name);
