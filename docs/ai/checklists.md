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

## Neues Projekt

Wenn ein komplett neues Projekt aus diesem Template entstehen soll — leer oder mit einer schon feststehenden
Idee, das Formular `CONFIG.md` deckt beides ab:

0. Projekt per `git clone <Template-URL> <projekt>` anlegen, damit Projekt und Template eine gemeinsame
   Git-Historie teilen (Voraussetzung für spätere Updates per Merge, siehe § „Template-Update" unten); danach
   `cd <projekt> && git remote rename origin template && git remote add origin <eigene-Repo-URL>`.
1. `CONFIG.md` im Repo-Root ausfüllen — alles optional, leer lassen ist gültig (Kommentare je Zeile erklären,
   was bei „leer" passiert). Bei Unklarheit mit {{AUFTRAGGEBER}} kurz rückfragen statt zu raten.
2. `python .claude/scripts/new-project.py --dry-run` ausführen, Plan (Werte, zu entfernende Dateien,
   Logging-Schalter, offene Platzhalter) gegen {{AUFTRAGGEBER}} prüfen.
3. `python .claude/scripts/new-project.py --apply` ausführen: ersetzt Platzhalter im ganzen Repo (außer
   `CONFIG.md`, `docs/ai/checklists.md`, `.claude/skills/new-project/SKILL.md`), entfernt nicht genutzte
   Werkzeug-Dateien (nur wenn `KI-Werkzeuge` gesetzt ist), setzt `AI_LOG`/`AI_LOG_LEVEL` in `AGENTS.md` und
   schreibt die Werte (und bei vorhandenem Remote `template` den Basis-Commit) in `.claude/template.json`.
4. Aus den `CONFIG.md`-Abschnitten befüllen: `docs/project/project_description.md` (Ziel, Nutzer, Scope aus
   Features, Non-Scope, Risiken), `docs/project/architecture.md` (Architektur-Text), `docs/project/
   coding_rules.md` § „Stack-spezifisch" (aus Stack), erste Aufgaben aus Features nach `docs/ai/tasks.md`,
   offene Platzhalterwerte/Lücken nach `docs/ai/questions.md`, Stand nach `docs/ai/board.md`. Bei leerem
   `CONFIG.md` bleiben die Skelette bestehen — nur Name/Datum sind gesetzt.
5. Werkzeug-Verweise prüfen: `docs/README.md`-Index und `AGENTS.md`-Tabelle „Werkzeugspezifische
   Ergänzungsdateien" gegen die tatsächlich noch vorhandenen Dateien.
6. Ersten `docs/ai/ledger.md`-Eintrag „Projekt angelegt aus CONFIG.md" schreiben — mit allen Setzungen
   (eingesetzte Werte, entfernte Dateien, Logging-Schalter).
7. `python .claude/scripts/new-project.py --finish` ausführen (prüft die Vorbedingungen aus Schritt 4/6,
   entfernt danach `CONFIG.md`).
8. `grep -rn "{{" .` prüfen — nur `docs/ai/checklists.md`, `.claude/skills/new-project/SKILL.md` und die
   Scripte in `.claude/scripts/` (Code-Literale bzw. Kopfkommentare, siehe `no_replace` in
   `.claude/template.json`) dürfen noch Platzhalter zeigen, alles andere klären.
9. Commit per Pathspec nach Freigabe (Checkliste „Sitzungsabschluss").

## Projekt nachrüsten

Wenn ein bestehendes Repo (eigene Historie, kein Template-Klon) die Agentic-Coding-Grundausstattung
nachträglich bekommen soll:

1. Aus dem Template-Checkout heraus: `python <template>/.claude/scripts/consume-template.py --target
   <ziel-repo>` ausführen — kopiert `AGENTS.md`, die Werkzeug-Verweisdateien, `.claude/`, `docs/ai/`,
   `docs/project/`-Skelette, `CONFIG.md` u. a. ins Ziel, ohne dort etwas zu überschreiben (Ausnahmen/Details
   im Kopfkommentar des Scripts). Schreibt `.claude/template.json` mit Basis-Commit/Remote-URL des Templates
   und legt im Ziel den Remote `template` an.
2. Im Ziel-Repo weiterarbeiten: `git status` sichten, übersprungene Dateien (u. a. `README.md`,
   `.gitignore`-Vorschlag) von Hand zusammenführen.
3. Bestand analysieren — nicht raten, am Code prüfen: Name, Stack, Struktur, Tests, Befehle, CI.
4. `CONFIG.md` mit dem gefundenen IST-Zustand befüllen, dann `python .claude/scripts/new-project.py --apply`
   ausführen (ersetzt Platzhalter, entfernt nicht genutzte Werkzeug-Dateien, setzt Werte).
5. `docs/project/*` mit dem echten IST-Zustand befüllen (nicht raten), `.gitignore`-Vorschläge übernehmen, im
   Projekt-`README.md` einen Abschnitt „Zusammenarbeit mit KI-Assistenten" ergänzen (Verweis `AGENTS.md`,
   `docs/ai/board.md`).
6. Ersten `docs/ai/board.md`-Stand und `docs/ai/ledger.md`-Eintrag schreiben, danach
   `python .claude/scripts/new-project.py --finish` ausführen.
7. Commit per Pathspec nach Freigabe.
8. `python .claude/scripts/template-update.py --graft` ausführen (nach Freigabe) — stellt per leerem
   Merge-Commit eine gemeinsame Historie mit dem Template her, ohne den Arbeitsbaum zu verändern;
   Voraussetzung für spätere `/template-update`-Läufe.

## Template-Update

Wenn Änderungen aus dem Template (übergeordnetes Vorlagen-Repo, per Remote „template" verbunden) in ein
bereits laufendes, abgeleitetes Projekt nachgezogen werden sollen — die eingesetzten Platzhalterwerte
(Projektname, Auftraggeber, Befehle, …) und die projektspezifische Doku (`docs/project/`, `docs/ai/`-
Arbeitsdateien, README) bleiben dabei erhalten:

1. Verfügbare Änderungen abrufen (fetch) und sichten: wie viele Commits, welche Dateien betroffen.
2. Prüfen, welche der betroffenen Dateien projektspezifisch sind (bleiben unverändert) und welche die
   Template-Logik übernehmen sollen.
3. Änderungen per Merge einspielen.
4. Bei Konflikten: projektspezifische Dateien/Bereiche (siehe `keep_local` in `.claude/template.json`)
   gewinnen automatisch; übrige Konflikte von Hand auflösen — Template-Logik in `.claude/`, `AGENTS.md`,
   `CLAUDE.md` und den Checklisten übernehmen, projektspezifische Zeilen (echte Werte, eigene Regeln)
   erhalten.
5. In den vom Update berührten Dateien Platzhalter durch die bereits im Projekt eingesetzten echten Werte
   ersetzen (kommt z. B. vor, wenn das Template eine neue Datei mit `{{PROJEKTNAME}}` mitbringt).
6. Prüfen: keine verbleibenden Platzhalter außer den bekannten Fundstellen in den Checklisten/Skills selbst,
   Konfigurationsdateien weiterhin gültig, Logging weiterhin funktionsfähig.
7. Commit per Pathspec.
8. Den nachgezogenen Basis-Commit des Templates in `.claude/template.json` fortschreiben, damit das nächste
   Update wieder ab diesem Stand vergleicht.
