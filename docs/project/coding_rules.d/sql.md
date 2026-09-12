# Coding-Regeln — SQL und Datenbank

Regeln für Schemaänderungen und Datenbankzugriff aus Anwendungscode.

## Sprache und Stil
- Bezeichner (Tabellen, Spalten) konsistent in `snake_case`, Plural für Tabellen, Singular für Spalten.
- Migrationen versioniert benennen (fortlaufende Nummer oder Zeitstempel + Beschreibung), eine Datei je
  Änderung.

## Struktur
- Migrationen idempotent schreiben (`IF NOT EXISTS`/Prüfung auf Vorhandensein), ein erneuter Lauf auf
  migriertem Stand darf nicht scheitern.
- Jede Fremdschlüsselspalte bekommt einen Index, sonst werden Joins/Lösch-Kaskaden langsam.
- Rollback/Down-Migration zu jeder Migration mitliefern, wenn das Migrationswerkzeug es unterstützt.

## Typisierung / Fehlerbehandlung
- Kein `SELECT *` in Anwendungscode — Spalten explizit benennen, damit Schemaänderungen auffallen.
- Mehrstufige Schreibvorgänge in einer Transaktion bündeln, kein manuelles Nachziehen bei Teilfehlern.
- Zeitstempel in UTC speichern, Zeitzonenumrechnung erst in der Präsentationsschicht.

## Werkzeuge
- Migrationswerkzeug projektabhängig (z. B. Flyway, Prisma Migrate, Alembic) — eines konsequent nutzen, nicht
  mischen.

## Fallstricke
- Keine Anwendungslogik in Stored Procedures/Triggern verstecken, die im Anwendungscode nicht sichtbar ist.
- Spaltentyp-Änderungen an großen Tabellen auf Sperrverhalten/Laufzeit prüfen, bevor sie live ausgeführt werden.
