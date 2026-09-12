Konfiguration für die Zusammenarbeit mit KI-Assistenten in diesem Projekt. Die Datei **bleibt dauerhaft im
Repo**: Der Abschnitt „Betrieb" wirkt in jeder Sitzung und darf jederzeit geändert werden, der Abschnitt
„Einrichtung" wird einmalig beim Anlegen gelesen und dokumentiert danach, mit welchen Werten das Projekt
entstanden ist.

Format: `Schlüssel: Wert`, alles ab der ersten runden Klammer ist Kommentar und wird abgeschnitten — Werte
daher ohne Klammern schreiben. Einrückung und Groß-/Kleinschreibung der Schlüssel sind egal. Alles ist
optional; leer lassen ist gültig und bedeutet jeweils den in Klammern genannten Standard.

## Betrieb

Gilt laufend. Der Orchestrator liest diesen Abschnitt zu Beginn jeder Sitzung.

    Orchestrator-Modell: opus (opus | sonnet | haiku | inherit — Modell der Hauptsession, steuert `model` in `.claude/settings.json`; Default „opus", weil der Orchestrator plant, prüft und entscheidet)
    Commit-Verhalten: fragen (automatisch | fragen | manuell — wie der Orchestrator mit der Checkliste „Aufgabe abschließen" umgeht: automatisch = committet abgenommene Arbeit selbst, fragen = schlägt den Commit vor und wartet auf Zustimmung, manuell = nur auf ausdrückliche Anweisung)
    Logging: aus (aus | ein — steuert `AI_LOG` in `AGENTS.md`)
    Logging-Tiefe: INFO (DEBUG | INFO | WARN | ERROR — steuert `AI_LOG_LEVEL` in `AGENTS.md`)
    Wartung: aus (aus | ein — wiederkehrende Wartung; „aus" entfernt `.claude/maintenance/`, den Skill `/run-maintenance`, den Agenten `maintenance-orchestrator` und den Fälligkeits-Hook)
    Wartungsaufgaben: kurz=14, docs=30, deps=90 (nur bei „Wartung: ein"; Aufgabe=Intervall in Tagen, weggelassene Aufgabe wird deaktiviert; schreibt `.claude/maintenance/status.json`)
    Wartungsberichte: intern (intern | docs — intern = `.claude/maintenance/reports/`, gitignored; docs = `docs/maintenance/`, versioniert und im Doku-Index sichtbar)
    Code-Optimierung: aus (aus | ein | streng — ein = eine Runde über frisch geschriebenen Code (kürzer, lesbarer); streng = bis zu zwei Runden, zusätzlich Geschwindigkeit und Speicher; „aus" entfernt den Agenten `optimizer`)

## Einrichtung

Wird beim Anlegen des Projekts einmalig gelesen (`/create-project`). Danach bleiben die Werte als Nachweis
stehen; eine Änderung hier wirkt nicht rückwirkend.

    Projektname: (Default „MyApp", wenn leer)
    Auftraggeber: (eigener Name; bleibt Platzhalter `{{AUFTRAGGEBER}}`, wenn leer)
    Orchestrator: (Default „Fable", wenn leer)
    Sprache: (Default „Deutsch", wenn leer — nur Hinweis für die Doku-Befüllung, kein Platzhalter im Repo)
    KI-Werkzeuge: (Kommaliste der Werkzeuge, die BLEIBEN sollen, aus: Claude Code, Copilot, Cursor, Aider, Gemini CLI, ChatGPT/Codex, Ollama; leer = alle behalten, nichts wird entfernt)
    Stack: (bleibt Platzhalter `{{STACK}}` in coding_rules.md, wenn leer)
    Coding-Guidelines: (Kommaliste der Regelsätze, die das Projekt übernehmen soll, z. B. `php, vue, tailwind`; verfügbar sind bash, csharp, go, nuxt, php, python, sql, tailwind, typescript, vue. Leer = keine — später jederzeit per `python .claude/scripts/guidelines.py --add <kennung>` aus dem Template nachladbar)
    Install-Befehl: (bleibt Platzhalter `{{INSTALL_BEFEHL}}` in `ci.yml`/`setup.md`, wenn leer)
    Dev-Start-Befehl: (bleibt Platzhalter `{{DEV_START_BEFEHL}}` in `setup.md`, wenn leer)
    Lint-Befehl: (bleibt Platzhalter `{{LINT_BEFEHL}}` in `ci.yml`/`testing.md`, wenn leer)
    Typecheck-Befehl: (bleibt Platzhalter `{{TYPECHECK_BEFEHL}}` in `ci.yml`/`testing.md`, wenn leer)
    Test-Befehl: (bleibt Platzhalter `{{TEST_BEFEHL}}` in `ci.yml`/`testing.md`, wenn leer)
    E2E-Befehl: (bleibt Platzhalter `{{E2E_BEFEHL}}` in `testing.md`/`setup.md`, wenn leer)
    Code-Analyse: fragen (nur Weg 2 „Projekt nachrüsten": nein = nur `docs/project/` aus dem Code befüllen | vorschlagen = danach zusätzlich den Bestand prüfen und Verbesserungen in `docs/ai/backlog.md` sammeln | fragen = nach der Doku im Chat nachfragen, Default)
    Struktur-Migration: fragen (nur Weg 2: ja = vorhandene KI-Arbeitsordner und -Regeldateien auf die Template-Struktur umstellen und zusammenführen | nein = nur fehlende Dateien ergänzen, vorhandene unangetastet lassen | fragen = Plan zeigen und im Chat nachfragen, Default)
    Alter Orchestrator-Name: (nur bei Struktur-Migration: bisher im Projekt verwendeter Rufname, z. B. der Name des alten KI-Ordners; wird projektweit durch den Wert von `Orchestrator` ersetzt. Leer = das Migrations-Script schlägt erkannte Kandidaten vor)

## Ziel
(Frage: welches Problem löst das Projekt, in ein bis zwei Sätzen? Leer = `project_description.md` bleibt
Skelett.)

## Nutzer
(Frage: wer nutzt das Ergebnis, und wie? Leer = `project_description.md` bleibt Skelett.)

## Features
(Erste Features als Liste, eine Zeile je Punkt mit „- ". Leer = keine ersten Einträge in `docs/ai/tasks.md`.)

## Non-Scope
(Was ausdrücklich NICHT dazugehört, auch wenn es naheliegt. Leer = `project_description.md` bleibt Skelett.)

## Architektur
(Grober Aufbau/Datenfluss, falls schon bekannt. Leer = `architecture.md` bleibt Skelett.)

## Risiken
(Bekannte Risiken/Unsicherheiten zum Start. Leer = `project_description.md` bleibt Skelett.)

## Sonstiges
(Alles andere, was der Assistent beim Anlegen wissen sollte. Leer = ohne Auswirkung.)
