> Datenstand: {{DATUM}} – Status: Vorlage, noch nicht projektspezifisch

# Checklisten für die Zusammenarbeit

Werkzeugneutrale Arbeitsanweisungen (gelten für jeden Assistenten, siehe `AGENTS.md`). {{AUFTRAGGEBER}} kann sie
wörtlich als Anweisung geben, z. B. „Führe die Checkliste Sitzungsabschluss aus (`docs/ai/checklists.md` §
Sitzungsabschluss)". Welche zusätzliche Mechanik ein bestimmtes Werkzeug dafür anbietet (automatisierter
Aufruf, Ablauf in einer separaten Session o. Ä.), steht in der jeweiligen werkzeugspezifischen Ergänzungsdatei
(siehe `AGENTS.md` § „Werkzeugspezifische Ergänzungsdateien"), nicht in dieser Checkliste.

## Sitzungsabschluss

Läuft immer im Hauptkontext (Orchestrator), nie bei einem Worker.

0. **Entwürfe auslagern:** Einen Ledger-Entwurf von einem Worker (zweite Session/günstigeres Modell) mit Auftrag
   „nur Entwurf, nichts committen" schreiben lassen; der Orchestrator liest den Entwurf, prüft ihn gegen die
   tatsächlichen Belege und übernimmt ihn (gekürzt/korrigiert).
1. **Belege sammeln:** Commit-Hashes, Testläufe/Ausgabezeilen, Dateipfade mit Größe, Rückmeldungen von Workern.
   „Fertig" nur mit Beleg (`AGENTS.md`).
2. **`docs/ai/ledger.md`:** neue Sitzung/neuer Lauf **oben** (`## YYYY-MM-DD (n. Lauf) — Titel`), Stichpunkte mit
   Belegen, was offen blieb.
3. **`docs/ai/tasks.md`:** erledigte Aufgaben mit Marker (✅/🔄/❓) kommentieren. Aufgaben unter „nur für
   {{AUFTRAGGEBER}}" nur hinzufügen/präzisieren/als erledigt markieren, wenn {{AUFTRAGGEBER}} es meldet — nie
   ausführen.
4. **`docs/ai/questions.md`:** neue Fragen oben (fortlaufende Nummern), dringende markiert, je Frage eigene
   `* Antwort:`-Zeile, keine Tabellen, ~72 Zeichen Zeilenumbruch. Beantwortete Fragen verbuchen (Bestätigung
   darunter), unter „Erledigt" zusammenfassen, im nächsten Lauf nach `questions_archive.md` verschieben.
5. **Ledger verdichten:** ältere Einträge zusammenfassen (Regeln im Ledger-Kopf); Commit-Hashes, Nummern,
   Versionen, Pfade bleiben immer erhalten.
6. **Doku-Index:** neue Dateien in `docs/README.md` eintragen; Datenstand-Zeilen der geänderten Dateien prüfen.
7. **Commit:** `git add <pathspec …>` (nie ein catch-all), kurze Message im Repo-Stil; Secrets/Zip/Originalfotos
   bleiben draußen (`.gitignore` prüfen). Fremde uncommittete Änderungen anderer Sitzungen nicht stillschweigend
   mitnehmen — sichten, dann entscheiden.
8. **Abschlussmeldung an {{AUFTRAGGEBER}}:** Ergebnis zuerst, Belege (Hash, Zahlen), offene Punkte/Fragen mit
   Nummern.
9. **Logging (falls eingeschaltet, `AGENTS.md` § Logging):** Commit als `[orchestrator] [commit] <hash> <message>`,
   Abschluss als `[orchestrator] [session] ende · <Kurzbilanz>` schreiben — das Log ist Mitschnitt, kein
   Ersatz für Ledger oder Beleg.

## Delegation

Bewährte Arbeitsweise: das teure/starke Modell (Orchestrator) plant, integriert und prüft; die breite Arbeit
machen parallele Worker (günstigeres/schnelleres Modell). So bleibt der Kontext des Orchestrators klein und die
Arbeit bezahlbar (siehe `AGENTS.md` § Modell-/Kostenlogik).

- **Wann delegieren:** Codebase-Analysen über mehrere Verzeichnisse, Web-/Doku-Recherche, unabhängige
  Baustellen (mehrere Endpunkte/Komponenten/Dateien), Routine-Doku-Pflege.
- **Nicht delegieren:** kleine Einzeldatei-Fixes, alles, was `docs/ai/` beschreibt (nur der Orchestrator
  schreibt dort), finale Commits, finale Urteile/Freigaben.
- **Auftrags-Regeln:** jeder Auftrag nennt Kontext (2–3 Sätze), konkreten Liefergegenstand, Format des
  Ergebnisses, was zu ignorieren ist (Build-Ordner, `node_modules`, `.git`, generierte Dateien).
- Unabhängige Worker **immer gleichzeitig** starten, nicht nacheinander.
- Worker-Ergebnisse sind Rohmaterial: der Orchestrator verifiziert Kernaussagen stichprobenartig am Code, bevor
  sie in Board, Doku oder Entscheidungen wandern.
- Ein Worker, der sich festgefressen hat, wird nicht endlos weitergefüttert — Auftrag schärfen und neu starten
  ist günstiger.
- Nach jeder Welle: Lint + Typecheck laufen lassen, betroffene Funktionen real ausprobieren; „fertig" nur mit
  Beleg; Ledger nachziehen (Checkliste „Sitzungsabschluss").
- Bei eingeschaltetem Logging (`AGENTS.md` § Logging): vor jeder Welle die Entscheidung als
  `[orchestrator] [decision]` schreiben, jede Delegation als `[delegate]`, Start/Ende der Worker als
  `[start]`/`[end]` — sofern das Werkzeug das nicht automatisch tut (Claude Code: Hooks, `CLAUDE.md` § 7).

## Doku-Nachzug

Nach jeder Feature-Welle, jedem produktionsrelevanten Bugfix:

- Neue Schnittstelle/neues Konzept/neue Tabelle → `docs/project/architecture.md` bzw. `features.md` ergänzen
  (knapp, im vorhandenen Stil).
- Neue Konvention gelernt (z. B. eine Framework-Falle) → `docs/project/coding_rules.md`, als Regel formuliert,
  nicht als Anekdote.
- Neue/geänderte Tests → `docs/project/testing.md`.
- `AGENTS.md`/`CLAUDE.md` nur anfassen, wenn sich Grundregeln ändern.
- Schwere Fehler (Build-/Startfehler, Produktionsausfälle, Sicherheitsrelevantes) nach
  `docs/project/incidents/README.md` dokumentieren.
- Grundsatz: Doku beschreibt den IST-Zustand, nicht den Wunsch. Was noch nicht gebaut ist, gehört auf die
  Umbauliste oder ins Fragen-Board. Kein Doku-Eintrag ohne Prüfung am Code.

## Idee → Projekt

Wenn aus einer Idee ein neues Projekt entstehen soll:

1. Interview mit {{AUFTRAGGEBER}}: Ziel, Nutzer/Zielgruppe, Scope und Non-Scope, gewünschter Stack, bekannte
   Risiken/Unsicherheiten.
2. Ergebnis in `docs/project/project_description.md` (Ziel, Nutzer, Scope/Non-Scope, Erfolgskriterien) und
   `docs/project/architecture.md` (grober Aufbau, Datenfluss) festhalten.
3. Erste Aufgaben in `docs/ai/tasks.md` anlegen, offene Entscheidungen in `docs/ai/questions.md`.
4. `docs/ai/board.md` mit dem neuen Stand aktualisieren.

## Template anpassen

Wenn dieses Template auf ein konkretes Projekt zugeschnitten wird:

1. Alle Platzhalter (`{{PROJEKTNAME}}`, `{{AUFTRAGGEBER}}`, `{{ORCHESTRATOR}}`, `{{STACK}}`, `{{DATUM}}`) im
   ganzen Repo suchen und durch echte Werte ersetzen (`grep -rn "{{"`).
2. Stack-spezifische Regeln in `docs/project/coding_rules.md` § „Stack-spezifisch" ergänzen (Sprache, Layer,
   Typisierung, Migrationskonvention, Linter/Formatter).
3. `.github/workflows/ci.yml` auf die echten Lint-/Typecheck-/Testbefehle des Projekts umstellen.
4. Nicht benötigte Vorlagendateien entfernen (z. B. Beispiel-Agenten für einen nicht genutzten Stack) und im
   Doku-Index (`docs/README.md`) nachziehen.
5. Jede Doku-Datei bekommt einen echten Datenstand (`YYYY-MM-DD`) statt „Status: Vorlage".
6. Abschlusscheck: `docs/ai/board.md` mit dem realen Projektstart-Stand befüllen, ersten Eintrag in
   `docs/ai/ledger.md` schreiben.
