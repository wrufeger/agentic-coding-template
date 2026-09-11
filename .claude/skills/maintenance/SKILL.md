---
name: maintenance
description: Wiederkehrende Wartung, fälligkeitsgesteuert oder per Argument, läuft im maintenance-orchestrator.
context: fork
agent: maintenance-orchestrator
model: claude-sonnet-5
disable-model-invocation: true
argument-hint: "[kurz|docs|deps|alle]"
---

# Wartung (läuft im Sub-Agenten `maintenance-orchestrator`)

Dieser Skill läuft **nicht** im Hauptkontext, sondern startet den Sub-Agenten `maintenance-orchestrator`
(`.claude/agents/maintenance-orchestrator.md`) mit dem übergebenen Argument.

## Argumente
- Ohne Argument: fälligkeitsgesteuert anhand `.claude/maintenance/status.json`.
- `kurz`: nur Kurzaudit (`git status`, Pflichtläufe aus `docs/project/testing.md`).
- `docs`: nur Doku-Audit (Fan-out wie Skill `/docs-audit`).
- `deps`: nur Abhängigkeits-Check.
- `alle`: alle Aufgaben unabhängig von der Fälligkeit.

## Headless-Runner
Für automatisierte/geplante Läufe außerhalb einer interaktiven Session: `.claude/maintenance/run-maintenance.ps1`
(Windows) bzw. `.claude/maintenance/run-maintenance.sh` (POSIX) — siehe `.claude/maintenance/README.md`.

## Nach dem Lauf (Hauptkontext)
- Bericht `.claude/maintenance/reports/YYYY-MM-DD.md` und die Rückgabe des Worker-Orchestrators prüfen.
- Vorschläge in `docs/ai/tasks.md`/`questions.md` einarbeiten, `docs/ai/ledger.md` ergänzen (Skill
  `/session-wrapup`), Commit per Pathspec.
