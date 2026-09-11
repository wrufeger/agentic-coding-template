Vor dem ersten Assistenten-Aufruf ausfüllen — alles optional, leer lassen ist gültig (siehe Kommentare je
Zeile). Wird vom Skill `/new-project` gelesen und danach automatisch entfernt (`new-project.py --finish`).
Format: `Schlüssel: Wert` in dieser Kopfliste, `## Abschnitt` mit Freitext darunter. Alles ab der ersten
runden Klammer gilt als Kommentar und wird abgeschnitten — Werte daher ohne Klammern schreiben.

Projektname: (Default „MyApp", wenn leer)
Auftraggeber: (eigener Name; bleibt Platzhalter `{{AUFTRAGGEBER}}`, wenn leer)
Orchestrator: (Default „Fable", wenn leer)
Sprache: (Default „Deutsch", wenn leer — nur Hinweis für die Doku-Befüllung, kein Platzhalter im Repo)
KI-Werkzeuge: (Kommaliste der Werkzeuge, die BLEIBEN sollen, aus: Claude Code, Copilot, Cursor, Aider, Gemini CLI, ChatGPT/Codex, Ollama; leer = alle behalten, nichts wird entfernt)
Stack: (bleibt Platzhalter `{{STACK}}` in coding_rules.md, wenn leer)
Logging: aus (aus | ein — steuert `AI_LOG` in `AGENTS.md`)
Logging-Tiefe: INFO (DEBUG | INFO | WARN | ERROR — steuert `AI_LOG_LEVEL` in `AGENTS.md`)
Install-Befehl: (bleibt Platzhalter `{{INSTALL_BEFEHL}}` in `ci.yml`/`setup.md`, wenn leer)
Dev-Start-Befehl: (bleibt Platzhalter `{{DEV_START_BEFEHL}}` in `setup.md`, wenn leer)
Lint-Befehl: (bleibt Platzhalter `{{LINT_BEFEHL}}` in `ci.yml`/`testing.md`, wenn leer)
Typecheck-Befehl: (bleibt Platzhalter `{{TYPECHECK_BEFEHL}}` in `ci.yml`/`testing.md`, wenn leer)
Test-Befehl: (bleibt Platzhalter `{{TEST_BEFEHL}}` in `ci.yml`/`testing.md`, wenn leer)
E2E-Befehl: (bleibt Platzhalter `{{E2E_BEFEHL}}` in `testing.md`/`setup.md`, wenn leer)

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
