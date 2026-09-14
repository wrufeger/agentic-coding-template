---
name: create-project
description: Checkliste Neues Projekt - AI-CONFIG.md einlesen, Platzhalter/Werkzeugdateien/Logging setzen, Doku aus CONFIG befüllen.
---

# Neues Projekt

Setzt die werkzeugneutrale Checkliste „Neues Projekt" aus `docs/ai/checklists.md` um (ersetzt die früheren
Skills `/adapt-template` und `/new-idea`). Läuft im Hauptkontext, da es Entscheidungen und Rückfragen mit
{{AUFTRAGGEBER}} braucht. Mechanik: `.claude/scripts/create-project.py`.

## Ablauf

0. **Läuft das hier im Template-Checkout selbst?** (Marker `is_template` in `.claude/template.json`.) Dann
   muss ein eigener Branch aktiv sein — `git switch -c projekt/<name>`. Auf `main`/`master` bricht
   `--apply` ab, weil es sonst das Template zerstören würde; `--dry-run` weist vorher darauf hin. Auf einem
   eigenen Branch entsteht das Projekt als Branch des Templates: Basis-Commit aus dem Standard-Branch,
   spätere `/update-template`-Läufe mergen von dort, ein Remote ist dafür nicht nötig.
1. **Leeres Projekt oder kurzes Interview?** Diese Frage kommt **immer**, außer in zwei Fällen: wenn
   {{AUFTRAGGEBER}} von sich aus „leeres Projekt" gesagt hat, oder wenn `AI-CONFIG.md` schon von Hand
   ausgefüllt wurde (dann steht die Antwort dort und wird nicht erneut erfragt).

   > Soll ein leeres Projekt entstehen — nur das Gerüst mit Standardwerten, das du später selbst ausfüllst?
   > a) nein, vier kurze Fragen jetzt beantworten (Empfehlung)
   > b) ja, leer anlegen — Projektname „MyApp", `AI-CONFIG.md` bleibt unausgefüllt

   Bei **b)** direkt zu Schritt 2. Bei **a)** diese vier Fragen stellen — in Claude Code als Auswahl, sonst
   als nummerierte Liste im Chat. Alle vier auf einmal, nicht nacheinander:

   1. **Projektname?** → `AI-CONFIG.md` § Projekt, `Projektname`
   2. **Welche KI-Werkzeuge sollen bleiben?** (Claude Code · Copilot · Cursor · Aider · Gemini CLI ·
      ChatGPT/Codex · Ollama; leer = alle behalten) → `KI-Werkzeuge`. Die Dateien der nicht genannten
      Werkzeuge entfernt Schritt 3.
   3. **Welcher Stack?** Ein Satz genügt („Nuxt 4 + MariaDB"). → `Stack`. Daraus **im selben Zug die
      passenden Regelsätze vorschlagen** (`Coding-Guidelines`, Kennungen aus `docs/project/coding_rules.d/`)
      und bestätigen lassen — keine eigene Frage, aber auch nicht stillschweigend setzen.
   4. **Worum geht es?** Ein bis zwei Sätze, welches Problem das Projekt löst. → Abschnitt `## Ziel`

   Antworten **in `AI-CONFIG.md` eintragen**, nicht nur merken — die Datei ist die Quelle und bleibt im
   Projekt. Danach in einem Satz sagen, was sonst auf Standard steht (Auftraggeber, Orchestrator-Name,
   Logging, Wartung) und dass sich das dort jederzeit ändern lässt.

2. `python .claude/scripts/create-project.py --dry-run` ausführen und den Plan (Werte, zu entfernende Dateien,
   Logging-Schalter, offene Platzhalter) zeigen. Bei echten Unklarheiten (z. B. mehrdeutige
   `KI-Werkzeuge`-Angabe) fragen statt raten.
3. `python .claude/scripts/create-project.py --apply` ausführen.
4. Aus den `AI-CONFIG.md`-Abschnitten (in der `--apply`-Ausgabe noch einmal zusammengefasst) befüllen:
   - `docs/project/project_description.md`: Ziel, Nutzer, Scope (aus Features), Non-Scope, Risiken.
   - `docs/project/architecture.md`: Architektur-Abschnitt als Text/Grobskizze.
   - `docs/project/coding_rules.md` § „Stack-spezifisch": aus dem Stack-Feld.
   - `docs/ai/tasks.md`: erste Aufgaben aus den Features.
   - `docs/ai/questions.md`: offene Platzhalterwerte (siehe „Offene Platzhalter" in der `--apply`-Ausgabe)
     und sonstige Lücken als Fragen an {{AUFTRAGGEBER}}.
   - `docs/ai/board.md`: aktuellen Stand.
   - `docs/README.md`: Datenstände der geänderten Dateien nachziehen.
   War `AI-CONFIG.md` leer: nur Name/Datum sind gesetzt, die Skelette bleiben unverändert stehen — das ist
   kein Fehler.
5. Werkzeug-Verweise prüfen: `docs/README.md`-Index und `AGENTS.md`-Tabelle „Werkzeugspezifische
   Ergänzungsdateien" gegen die tatsächlich noch vorhandenen Dateien (Script hat bereits Zeilen entfernter
   Werkzeuge entfernt — stichprobenartig gegenprüfen).
6. `docs/ai/ledger.md`-Eintrag „Projekt angelegt aus AI-CONFIG.md" schreiben, mit allen Setzungen (Werte,
   entfernte Dateien, Logging-Schalter aus der `--apply`-Ausgabe).
7. `python .claude/scripts/create-project.py --finish` ausführen (prüft vorher Schritt 4/6, schreibt danach
   `AI-CONFIG.md` fort statt sie zu löschen: Freitext-Abschnitte raus, Vermerk in Zeile 1, „Betrieb"/
   „Einrichtung" bleiben).
8. `grep -rn "{{" .` prüfen — nur die Scripte in `.claude/scripts/` (Code-Literale, Kopfkommentare; siehe
   `no_replace` in `.claude/template.json`) und `AI-CONFIG.md` dürfen noch Platzhalter zeigen.
9. **Globale Ablage anbieten** (`AI-CONFIG.md` → `Globale Ablage`): `nein` → überspringen.
   `agenten` / `agenten+skills` / `alles` → ohne Rückfrage `python .claude/scripts/install-global.py --plan
   --parts <entsprechend>` zeigen und nach Zustimmung `--apply` (mit `--force` nur, wenn
   {{AUFTRAGGEBER}} eine vorhandene Zieldatei ausdrücklich überschreiben will). `fragen` (Default) → **einmal**
   im Chat nachfragen: „Sollen Agenten-Rollen (und/oder `/commit`+`/audit-docs`, ein kurzer Regelauszug)
   zusätzlich nach `~/.claude/` gelegt werden, damit sie in allen Projekten dieses Rechners gelten? a) nein
   b) nur Agenten c) Agenten + Skills d) alles". Ohne Antwort **nicht** installieren — keine Standardantwort
   annehmen.
10. Commit per Pathspec nach Freigabe von {{AUFTRAGGEBER}} (Skill `/commit`).
11. **Einmal nachfragen:** „Ist die Einrichtung damit abgeschlossen, oder kommt noch etwas? a) abgeschlossen
    — Einrichtungswerkzeuge jetzt entfernen b) noch nicht — später mit `/finalize`". Bei a) den Skill
    `/finalize` gleich ausführen; bei b) bleibt alles liegen, ein Hinweis bei künftigen Sitzungsstarts
    erinnert daran.
