---
name: new-project
description: Checkliste Neues Projekt - CONFIG.md einlesen, Platzhalter/Werkzeugdateien/Logging setzen, Doku aus CONFIG befüllen.
---

# Neues Projekt

Setzt die werkzeugneutrale Checkliste „Neues Projekt" aus `docs/ai/checklists.md` um (ersetzt die früheren
Skills `/adapt-template` und `/new-idea`). Läuft im Hauptkontext, da es Entscheidungen und Rückfragen mit
{{AUFTRAGGEBER}} braucht. Mechanik: `.claude/scripts/new-project.py`.

## Ablauf

0. **Läuft das hier im Template-Checkout selbst?** (Marker `is_template` in `.claude/template.json`.) Dann
   muss ein eigener Branch aktiv sein — `git switch -c projekt/<name>`. Auf `main`/`master` bricht
   `--apply` ab, weil es sonst das Template zerstören würde; `--dry-run` weist vorher darauf hin. Auf einem
   eigenen Branch entsteht das Projekt als Branch des Templates: Basis-Commit aus dem Standard-Branch,
   spätere `/template-update`-Läufe mergen von dort, ein Remote ist dafür nicht nötig.
1. `python .claude/scripts/new-project.py --dry-run` ausführen und den Plan (Werte, zu entfernende Dateien,
   Logging-Schalter, offene Platzhalter) zeigen. Ist `CONFIG.md` leer oder fehlt sie: kurz nachfragen, ob
   {{AUFTRAGGEBER}} sie zuerst ausfüllen möchte oder bewusst mit Defaults (Projektname „MyApp", Orchestrator
   „Fable") weitermachen will — bei echten Unklarheiten (z. B. mehrdeutige `KI-Werkzeuge`-Angabe) fragen
   statt raten.
2. `python .claude/scripts/new-project.py --apply` ausführen.
3. Aus den `CONFIG.md`-Abschnitten (in der `--apply`-Ausgabe noch einmal zusammengefasst) befüllen:
   - `docs/project/project_description.md`: Ziel, Nutzer, Scope (aus Features), Non-Scope, Risiken.
   - `docs/project/architecture.md`: Architektur-Abschnitt als Text/Grobskizze.
   - `docs/project/coding_rules.md` § „Stack-spezifisch": aus dem Stack-Feld.
   - `docs/ai/tasks.md`: erste Aufgaben aus den Features.
   - `docs/ai/questions.md`: offene Platzhalterwerte (siehe „Offene Platzhalter" in der `--apply`-Ausgabe)
     und sonstige Lücken als Fragen an {{AUFTRAGGEBER}}.
   - `docs/ai/board.md`: aktuellen Stand.
   - `docs/README.md`: Datenstände der geänderten Dateien nachziehen.
   War `CONFIG.md` leer: nur Name/Datum sind gesetzt, die Skelette bleiben unverändert stehen — das ist
   kein Fehler.
4. Werkzeug-Verweise prüfen: `docs/README.md`-Index und `AGENTS.md`-Tabelle „Werkzeugspezifische
   Ergänzungsdateien" gegen die tatsächlich noch vorhandenen Dateien (Script hat bereits Zeilen entfernter
   Werkzeuge entfernt — stichprobenartig gegenprüfen).
5. `docs/ai/ledger.md`-Eintrag „Projekt angelegt aus CONFIG.md" schreiben, mit allen Setzungen (Werte,
   entfernte Dateien, Logging-Schalter aus der `--apply`-Ausgabe).
6. `python .claude/scripts/new-project.py --finish` ausführen (löscht `CONFIG.md`, prüft vorher Schritt 3/5).
7. `grep -rn "{{" .` prüfen — nur die Scripte in `.claude/scripts/` (Code-Literale, Kopfkommentare; siehe
   `no_replace` in `.claude/template.json`) und `CONFIG.md` dürfen noch Platzhalter zeigen.
8. Commit per Pathspec nach Freigabe von {{AUFTRAGGEBER}} (Skill `/commit`).
