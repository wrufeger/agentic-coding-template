# Coding rules — SQL

summary: query safety, transactions, indexing, naming, migrations, MySQL/MariaDB pitfalls

Rules for schema changes and database access from application code. Group IDs (`CR-sql-<name>`) are
stable and never reassigned; a group whose purpose no longer holds gets a new ID and is listed as
`retired:` in this header.

## `CR-sql-basics` — Query safety and schema discipline

summary: parametrized queries, transactions without network calls, UTC, indexing, no hidden logic, locking

- Use parametrized queries only — never build a query by concatenating values into the SQL string, in
  any language or driver.
- Never `SELECT *` in application code; name columns explicitly, so a schema change breaks visibly
  instead of silently changing what a query returns.
- Bundle multi-step writes into one transaction; don't reconcile partial failures by hand afterward.
- Make no network call inside a transaction that holds row locks: the locks last as long as the slowest
  remote answer. Resolve external values before the transaction opens (after the permission checks), cap the
  number of fetches per request and run them in parallel; helpers called inside the transaction get only
  resolved values. A retried transaction makes it worse, since the callback and every call in it runs again. In
  review ask: where does the transaction start and end, how many outside calls, how long at most.
- Store timestamps in UTC; convert to a time zone only in the presentation layer (on MySQL/MariaDB mind
  `CONVERT_TZ`, see `CR-sql-mariadb`).
- Add an index to every foreign-key column — without one, joins and cascading deletes degrade as the
  table grows.
- Keep application logic out of stored procedures and triggers; logic that isn't visible in the
  application code isn't reviewable.
- Check a column type change on a large table for lock behavior and expected runtime before running it
  live.

## `CR-sql-naming` — Identifier naming

summary: snake_case, plural tables, singular columns

- Name tables and columns in `snake_case`.
- Use the plural for table names, the singular for column names.

## `CR-sql-migrations` — Migration discipline

summary: versioned naming, idempotent, reversible, one tool

- Name migrations with a version (sequence number or timestamp) plus a description; one file per change.
- Write migrations idempotently (`IF NOT EXISTS` or an existence check) — running an already-migrated
  state again must not fail.
- Ship a down-migration with every migration where the migration tool supports it.
- Use one migration tool consistently (e.g. Flyway, Prisma Migrate, Alembic); don't mix.

## `CR-sql-mariadb` — MySQL and MariaDB (InnoDB) pitfalls

summary: gap locks on range writes, error 1020 under snapshot isolation, `LOCK IN SHARE MODE` instead of `FOR SHARE`, `ALTER` and ENUM changes on versioned tables, `CONVERT_TZ` without zone tables, cascade plus `SET NULL` on one row of a versioned table

- InnoDB (default isolation level `REPEATABLE READ`): a range `UPDATE` or `DELETE` on a table that others insert into
  takes gap locks and can deadlock with a concurrent `INSERT`. Read the ids first without a lock, then change by `WHERE
  id IN (…)`. It shows only with many rows and several concurrent writers, so a small test does not catch it.
- MariaDB 11.6.2 and later (`innodb_snapshot_isolation` is on by default): error 1020 ("record has changed since
  last read") aborts a locking read and an `UPDATE`/`DELETE` of a row changed after the transaction's snapshot. It
  also aborts the foreign-key check of an `INSERT` once the transaction has read anything without a lock and another
  transaction has since changed the parent row, in any column. 1020 rolls back the whole transaction: retry only the
  whole transaction, with growing, randomised waits, then give up with a clear error; effects outside the database
  are not rolled back. Locking the parent row (`FOR UPDATE`) before the first unlocked read avoids the foreign-key
  case. Safeguard: run every transaction through one retry helper or give it a marker comment stating why it needs
  none, and let a fast unit test find transactions with neither.
- MariaDB: a shared read lock is written `LOCK IN SHARE MODE`; the MySQL 8 form `FOR SHARE` is a syntax error
  there. A query builder's `forShare()` (Kysely, for one) emits the MySQL form, and the error shows only at run
  time against a real database: append the lock clause raw at the end of the query instead (Kysely:
  ``.modifyEnd(sql`lock in share mode`)``); MySQL 8 accepts that form too. `FOR UPDATE` is the same in both.
- MariaDB, system-versioned table: an `ALTER TABLE` that changes its columns is refused by default. Set
  `system_versioning_alter_history = KEEP` for the session just around the `ALTER`, on the same connection taken
  from the pool, and reset it in a `finally`; a migration run at application start otherwise aborts every start.
  `KEEP` leaves the history rows as they are, so a change that contradicts old values still fails (the `ENUM` case
  below).
- MariaDB, system-versioned table: dropping a value from an `ENUM` fails on history rows, including rows just
  replaced. Keep the value in the type, move the current rows, reject the old value in the application, and change
  the default with `ALTER COLUMN … SET DEFAULT`. Test the migration against a database that has such history rows.
- MySQL/MariaDB: `CONVERT_TZ` with zone names returns `NULL` without any error when the time-zone tables are not loaded
  (common on managed or container databases). Hand the offset in as a number, or do the conversion in application code.
- MariaDB, system-versioned table: deleting a parent row whose child rows cascade, where the child also has a
  self-reference with `ON DELETE SET NULL`, can write the same history row twice and fail with a duplicate-key error
  (reported; the affected versions are not known, so test on the one you run). Avoid it: within one transaction, a
  first statement removes the child rows, a second one removes the parent. A test builds a chain of at least two
  linked rows, because a single row does not trigger it.
