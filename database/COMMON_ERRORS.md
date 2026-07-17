# Common MySQL Errors and Fixes

### 1. `ERROR 1044 (42000): Access denied for user`
**Cause:** Your MySQL user doesn't have privileges on `certverify_db`, or you're running the script as a non-root user without `CREATE DATABASE` rights.
**Fix:** Run `schema.sql` as root (or a user with `CREATE`/`GRANT` privileges) first, then create/use the restricted `certverify_app` user only for the Flask app afterward.

---

### 2. `ERROR 1062 (23000): Duplicate entry 'admin' for key 'uq_admins_username'`
**Cause:** You ran `schema.sql` more than once without dropping tables first — the admin seed INSERT fails because the username already exists.
**Fix:** Either uncomment the `DROP TABLE IF EXISTS` block at the top of `schema.sql` (dev only), or simply skip re-running the seed INSERT statements if the tables already exist.

---

### 3. `ERROR 1406 (22001): Data too long for column 'certificate_hash' at row 1`
**Cause:** A hash string being inserted isn't exactly 64 characters (this is the exact bug we caught and fixed above — always verify hash length before inserting).
**Fix:** SHA-256 hex digests are ALWAYS 64 characters. If you see this error, print `len(your_hash_string)` in Python before inserting — it must equal 64.

---

### 4. `ERROR 1452 (23000): Cannot add or update a child row: a foreign key constraint fails`
**Cause:** You're trying to insert a `certificates` row referencing a `student_id` or `block_id` that doesn't exist yet.
**Fix:** Always insert the `students` row and the `blockchain_blocks` row FIRST (in that order), then insert the `certificates` row referencing their generated IDs. This is exactly why Phase 4's upload logic wraps all three inserts in a single DB transaction — if any step fails, everything rolls back and you never get an orphaned reference.

---

### 5. `ERROR 1215 (HY000): Cannot add foreign key constraint`
**Cause:** Usually a column type/charset mismatch between the FK column and the referenced column (e.g., referencing an `INT` column with a `BIGINT`, or different charset/collation between tables).
**Fix:** Ensure both sides of every FK use identical types (we use `INT` consistently for all internal IDs) and every table uses `utf8mb4_unicode_ci`. Also confirm both tables use the `InnoDB` engine — `MyISAM` does not support foreign keys at all.

---

### 6. `ERROR 1146 (42S02): Table 'certverify_db.certificates' doesn't exist`
**Cause:** Tables were created out of dependency order, or the `USE certverify_db;` statement was missed before running individual CREATE TABLE statements.
**Fix:** Always run the full `schema.sql` file top-to-bottom rather than copy-pasting individual CREATE TABLE blocks out of order.

---

### 7. `sqlalchemy.exc.OperationalError: (2003, "Can't connect to MySQL server")`
**Cause:** MySQL service isn't running, or Flask's `config.py` has wrong host/port.
**Fix:**
```bash
# Linux
sudo systemctl status mysql
sudo systemctl start mysql

# Windows (as admin, in services.msc or)
net start MySQL80
```
Then double check `DB_HOST='localhost'` and `DB_PORT=3306` in your Flask config.

---

### 8. `ERROR 1146` when inserting into `certificate_sequence` with `ON DUPLICATE KEY UPDATE`
**Cause:** Running `seed_data.sql`/`schema.sql` before the `certificate_sequence` table exists (out-of-order execution of statements from a partially-copied script).
**Fix:** Run the complete, unmodified `schema.sql` file — don't extract snippets.

---

### 9. Genesis block hash "mismatch" when Phase 3's Python code validates the chain
**Cause:** The `block_timestamp` stored in MySQL and the timestamp string your Python `Block` class uses to recompute the hash don't match EXACTLY (e.g., MySQL trims trailing zeros in microseconds, or Python formats the datetime differently — with/without the `T` separator, different microsecond padding, etc.)
**Fix:** This will be handled explicitly in Phase 3 — we will read back the timestamp from MySQL using the same format string every time (`'%Y-%m-%d %H:%M:%S.%f'`) rather than relying on Python's default `str(datetime)`, and we'll write a unit test that loads the Genesis Block from the DB and asserts the recomputed hash equals the stored `current_hash`.
