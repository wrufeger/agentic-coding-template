> Datenstand: {{DATUM}} – Status: Vorlage, noch nicht projektspezifisch

# Coding-Regeln — {{PROJEKTNAME}}

Generische Regeln gelten sofort; der Abschnitt „Stack-spezifisch" wird beim Anlegen des Projekts
(Checkliste „Neues Projekt", `docs/ai/checklists.md`) für {{STACK}} ausgefüllt.

## Generische Regeln (gelten unabhängig vom Stack)

- **Schichtentrennung:** klare Grenzen zwischen Datenzugriff, Geschäftslogik und Darstellung/API — keine
  Vermischung, die spätere Änderungen unnötig riskant macht.
- **Zentrale Typen:** Datentypen/Schemas an einer Stelle definieren und von dort importieren, nicht lokal
  duplizieren. Kein `any`/dynamisches „irgendwas" ohne Not — unbekannte Werte explizit prüfen (Narrowing),
  bevor sie verwendet werden.
- **Autoren-Stil respektieren:** bestehenden Code-Stil beibehalten, solange er kein echtes Problem verursacht.
  Nicht "modernisieren" ohne Anlass — Abweichungen vom vorhandenen Stil nur mit Begründung, und dann auf
  `docs/ai/backlog.md` vorschlagen statt im laufenden Auftrag durchzuziehen.
- **Sprachtrennung:** Dokumentation, UI-Texte und Kommentare in der im Projekt festgelegten Sprache (Standard
  in diesem Template: Deutsch); Code-Bezeichner (Variablen, Funktionen, Dateinamen) in Englisch.
- **Migrationen:** Schema-/Datenänderungen versioniert (eine Datei je Änderung, fortlaufend benannt) und
  idempotent — ein erneuter Lauf auf einem bereits migrierten Stand darf nicht scheitern oder Daten doppeln.
- **Fehlerbehandlung:** strukturiert und konsistent (ein Muster fürs ganze Projekt) statt Einzelfall-Try/Catch
  ohne erkennbares Schema; Fehlermeldungen an Nutzer/Aufrufer verständlich, technische Details nur in Logs.
- **Fehleranalysen:** schwere Fehler (Build-/Startfehler, Produktionsausfälle, sicherheitsrelevante Fehler,
  kritische Laufzeitfehler) nach dem Schema in `docs/project/incidents/README.md` dokumentieren.
- **Editorconfig/Formatierung:** `.editorconfig` im Repo-Root ist verbindlich (Zeilenenden LF, UTF-8,
  Einrückung siehe dort); ein projektweiter Formatter/Linter wird unten unter „Stack-spezifisch" eingetragen.
- **Abhängigkeiten:** Versions-Updates laufen über die konfigurierte Abhängigkeits-Automatisierung
  (`renovate.json`), keine manuellen Ad-hoc-Bumps ohne Grund.

## Vorgefertigte Regelsätze

Technologiespezifische Regeln liegen als Bausteine unter `coding_rules.d/` — ein Baustein je Sprache oder
Framework. Verwaltet werden sie mit `python .claude/scripts/guidelines.py` (`--list`, `--add <kennung>`,
`--remove <kennung>`); der folgende Block wird dabei automatisch geschrieben, hier nichts von Hand ändern.

<!-- guidelines:start -->
- [Shell-Skripte](coding_rules.d/bash.md) — Regeln für Bash-Skripte: Robustheit, Quoting, Prüfbarkeit durch Linter.
- [C#](coding_rules.d/csharp.md) — Regeln für modernes C# mit Nullable-Kontext, konsequent asynchronem Code und Re…
- [Go](coding_rules.d/go.md) — Regeln für idiomatisches Go: Fehlerbehandlung, kleine Interfaces, Kontextpropag…
- [Java](coding_rules.d/java.md) — Regeln für moderne Java-Versionen (LTS) mit Fokus auf Unveränderlichkeit, ausdr…
- [Nuxt](coding_rules.d/nuxt.md) — Regeln für Nuxt-Projekte: Verzeichniskonvention, Datenzugriff, sichere Konfigur…
- [PHP](coding_rules.d/php.md) — Regeln für moderne PHP-Versionen (8.x): Typisierung, PSR-12, sichere Datenbankz…
- [Python](coding_rules.d/python.md) — Regeln für Python 3 mit Typannotationen, Stdlib-first und automatisiertem Linti…
- [SQL und Datenbank](coding_rules.d/sql.md) — Regeln für Schemaänderungen und Datenbankzugriff aus Anwendungscode.
- [Tailwind CSS](coding_rules.d/tailwind.md) — Regeln für Utility-First-Styling mit Tailwind, meist innerhalb eines Frontend-F…
- [TypeScript](coding_rules.d/typescript.md) — Regeln für TypeScript im strict-Modus mit zentraler Typablage und sauberem Narr…
- [Vue 3](coding_rules.d/vue.md) — Regeln für Vue-3-Komponenten mit Composition API und `<script setup>`.
<!-- guidelines:end -->

## Stack-spezifisch (ausfüllen)

Hier steht, was **kein** Baustein abdeckt — die Eigenheiten genau dieses Projekts.

*(Beim Zuschneiden des Templates ergänzen: Programmiersprache(n), Verzeichnisstruktur/Aliasse, Typisierungs-
regeln des gewählten Typsystems, Migrationswerkzeug und Namenskonvention, Linter/Formatter samt Befehl,
projektspezifische Fallstricke, die {{AUFTRAGGEBER}} kennt.)*

- Sprache(n)/Framework: *(offen)*
- Verzeichnisstruktur/Aliasse: *(offen)*
- Typisierung: *(offen)*
- Migrationskonvention: *(offen)*
- Linter/Formatter: *(offen)*
- Bekannte Fallstricke: *(offen)*
