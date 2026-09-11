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

## Stack-spezifisch (ausfüllen)

*(Beim Zuschneiden des Templates ergänzen: Programmiersprache(n), Verzeichnisstruktur/Aliasse, Typisierungs-
regeln des gewählten Typsystems, Migrationswerkzeug und Namenskonvention, Linter/Formatter samt Befehl,
projektspezifische Fallstricke, die {{AUFTRAGGEBER}} kennt.)*

- Sprache(n)/Framework: *(offen)*
- Verzeichnisstruktur/Aliasse: *(offen)*
- Typisierung: *(offen)*
- Migrationskonvention: *(offen)*
- Linter/Formatter: *(offen)*
- Bekannte Fallstricke: *(offen)*
