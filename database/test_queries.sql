-- =====================================================================
-- Test / Verification Queries
-- Run these after schema.sql (and optionally seed_data.sql) to confirm
-- the database is set up correctly.
-- =====================================================================

USE certverify_db;

-- 1. Confirm all 6 tables exist
SHOW TABLES;
-- Expected: admins, blockchain_blocks, certificate_sequence,
--           certificates, students, verification_logs

-- 2. Confirm exactly one admin exists (or two, if seed_data.sql was run)
SELECT id, username, full_name, is_active, created_at FROM admins;

-- 3. Confirm the Genesis Block exists and looks correct
SELECT * FROM blockchain_blocks WHERE block_index = 0;
-- Expected: exactly 1 row, previous_hash and certificate_hash are 64 zeros,
-- current_hash = '0352a0f4aa338a25b3957d69ec7eb396b86800d9eafaf8a732af82d77f5aae04'

-- 4. Confirm hash column lengths are always exactly 64 (sanity check for
--    the kind of bug we found and fixed manually above)
SELECT
    id,
    block_index,
    CHAR_LENGTH(certificate_hash) AS cert_hash_len,
    CHAR_LENGTH(previous_hash)    AS prev_hash_len,
    CHAR_LENGTH(current_hash)     AS curr_hash_len
FROM blockchain_blocks;
-- Every row: all three lengths must equal 64

-- 5. Confirm foreign keys are correctly registered
SELECT
    TABLE_NAME, COLUMN_NAME, CONSTRAINT_NAME,
    REFERENCED_TABLE_NAME, REFERENCED_COLUMN_NAME
FROM information_schema.KEY_COLUMN_USAGE
WHERE TABLE_SCHEMA = 'certverify_db'
  AND REFERENCED_TABLE_NAME IS NOT NULL;
-- Expected 3 rows: certificates->students, certificates->blockchain_blocks,
-- certificates->admins

-- 6. Confirm unique constraints exist (duplicate-prevention check)
SELECT
    TABLE_NAME, CONSTRAINT_NAME, CONSTRAINT_TYPE
FROM information_schema.TABLE_CONSTRAINTS
WHERE TABLE_SCHEMA = 'certverify_db'
  AND CONSTRAINT_TYPE = 'UNIQUE'
ORDER BY TABLE_NAME;

-- 7. Try to insert a duplicate combined_hash manually to confirm the
--    UNIQUE constraint actually blocks it (run this only after at least
--    one certificate exists, i.e., after Phase 4 testing).
-- Expected result: ERROR 1062 Duplicate entry ... for key 'uq_certificates_combined_hash'
--
-- INSERT INTO certificates (certificate_id, student_id, course_name, grade,
--     issue_date, file_path, original_filename, file_hash, data_hash,
--     combined_hash, block_id)
-- SELECT 'CERT-2026-999999', student_id, course_name, grade, issue_date,
--     file_path, original_filename, file_hash, data_hash, combined_hash, block_id
-- FROM certificates LIMIT 1;

-- 8. Confirm sample student data loaded correctly (if seed_data.sql was run)
SELECT id, full_name, roll_number, course, year_of_passing FROM students;

-- 9. Confirm certificate_sequence initialized for current year
SELECT * FROM certificate_sequence;

-- 10. Simulate a "student with certificates cannot be deleted" check
--     (run only after at least one certificate exists)
-- Expected result: ERROR 1451 Cannot delete or update a parent row: a
-- foreign key constraint fails (fk_certificates_student)
--
-- DELETE FROM students WHERE id = 1;

-- 11. Row counts overview (quick health check)
SELECT
    (SELECT COUNT(*) FROM admins)              AS admin_count,
    (SELECT COUNT(*) FROM students)             AS student_count,
    (SELECT COUNT(*) FROM certificates)         AS certificate_count,
    (SELECT COUNT(*) FROM blockchain_blocks)    AS block_count,
    (SELECT COUNT(*) FROM verification_logs)    AS log_count;
