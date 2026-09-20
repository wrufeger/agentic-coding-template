# Coding rules — SQL

summary: query safety, transactions, indexing, naming, migrations

Rules for schema changes and database access from application code. Group IDs (`CR-sql-<name>`) are
stable and never reassigned; a group whose purpose no longer holds gets a new ID and is listed as
`retired:` in this header.

## `CR-sql-basics` — Query safety and schema discipline

summary: parametrized queries, transactions, UTC, indexing, no hidden logic, locking

- Use parametrized queries only — never build a query by concatenating values into the SQL string, in
  any language or driver.
- Never `SELECT *` in application code; name columns explicitly, so a schema change breaks visibly
  instead of silently changing what a query returns.
- Bundle multi-step writes into one transaction; don't reconcile partial failures by hand afterward.
- Store timestamps in UTC; convert to a time zone only in the presentation layer.
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
