# Database Setup Instructions

## Prerequisites
- MySQL Server 8.0 or higher installed and running
- MySQL client access (command line, MySQL Workbench, or phpMyAdmin)
- Know your MySQL root/admin credentials

## Step 1: Log in to MySQL

```bash
mysql -u root -p
```
Enter your root password when prompted.

## Step 2: Run the schema script

From the command line (recommended — runs the whole file in one shot):

```bash
mysql -u root -p < database/schema.sql
```

This will:
1. Create the `certverify_db` database (utf8mb4 charset).
2. Create all 6 tables in the correct dependency order.
3. Insert the default admin account (`admin` / `Admin@123`).
4. Insert the Genesis Block (`block_index = 0`).
5. Initialize the certificate ID sequence counter for 2026.

## Step 3: (Optional) Load sample demo data

```bash
mysql -u root -p < database/seed_data.sql
```
This adds 5 sample students and a second demo admin account (`registrar` / `Registrar@123`) so you have data to work with when testing Phases 4–8. It's safe to re-run — duplicates are skipped via `ON DUPLICATE KEY UPDATE`.

## Step 4: Create a dedicated MySQL application user (do NOT use root in the Flask app)

Using `root` for your Flask app is a bad practice we want to avoid, even in a college project — it's an easy, professional-looking touch to demonstrate least-privilege principles.

```sql
CREATE USER 'certverify_app'@'localhost' IDENTIFIED BY 'ChangeThisStrongPassword!23';
GRANT SELECT, INSERT, UPDATE, DELETE ON certverify_db.* TO 'certverify_app'@'localhost';
FLUSH PRIVILEGES;
```

Note: We deliberately do NOT grant `DROP`, `ALTER`, or `CREATE` to the app user — the running Flask app should never be able to modify table structure, only read/write rows. Schema changes should always go through `schema.sql`, run manually by a developer/DBA.

Use these `certverify_app` credentials in Phase 4's `config.py`, not root.

## Step 5: Verify the setup

```bash
mysql -u certverify_app -p certverify_db
```

Then run:
```sql
SHOW TABLES;
SELECT * FROM admins;
SELECT * FROM blockchain_blocks;
```

You should see 6 tables and exactly 1 row in `blockchain_blocks` (the Genesis Block, index 0).

## Step 6: Re-running the schema during development

If you need to reset the database while developing, uncomment the `DROP TABLE IF EXISTS` block at the top of `schema.sql` before re-running it. **Never do this against a database with real certificate data** — it is irreversible.
