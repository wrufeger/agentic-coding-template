---
name: act-run-maintenance
description: Wiederkehrende Wartung, fälligkeitsgesteuert oder per Argument, läuft im maintenance-orchestrator.
context: fork
agent: maintenance-orchestrator
model: claude-sonnet-5
disable-model-invocation: true
argument-hint: "[faellig|kurz|docs|deps|alle]"
---

# Wartung (läuft im Sub-Agenten `maintenance-orchestrator`)

**Optional:** per `AI-CONFIG.md` § „Wartung" abwählbar — bei „aus" entfernt `/create-project` diesen Skill samt
Agent, Ordner und Hook (siehe `.claude/maintenance/README.md`).

Dieser Skill läuft **nicht** im Hauptkontext, sondern startet den Sub-Agenten `maintenance-orchestrator`
(`.claude/agents/maintenance-orchestrator.md`) mit dem übergebenen Argument.

## Fälligkeit
Der `SessionStart`-Hook (`.claude/settings.json`) ruft bei jeder neuen Session automatisch
`maintenance-check.py --check --quiet` auf und meldet im Kontext, wenn Aufgaben fällig sind (sonst keine
Meldung). Das ist der Hinweis, `/run-maintenance` zu starten.

## Argumente
- Ohne Argument bzw. `faellig`: nur was `.claude/scripts/maintenance-check.py --check` als fällig meldet
  (anhand `.claude/maintenance/status.json`).
- `kurz`: nur Kurzaudit (`git status`, Pflichtläufe aus `docs/project/testing.md`), unabhängig von der Fälligkeit.
- `docs`: nur Doku-Audit (Fan-out wie Skill `/audit-docs`), unabhängig von der Fälligkeit.
- `deps`: nur Abhängigkeits-Check, unabhängig von der Fälligkeit.
- `alle`: alle konfigurierten Aufgaben unabhängig von der Fälligkeit.

## Headless-Runner
Für automatisierte/geplante Läufe außerhalb einer interaktiven Session: `.claude/maintenance/run-maintenance.ps1`
(Windows) bzw. `.claude/maintenance/run-maintenance.sh` (POSIX) — siehe `.claude/maintenance/README.md`.

## Nach dem Lauf (Hauptkontext)
- Bericht prüfen (Ablageort aus `AI-CONFIG.md` → `Wartungsberichte`: `intern` →
  `.claude/maintenance/reports/YYYY-MM-DD.md`, gitignored; `docs` → `docs/maintenance/YYYY-MM-DD.md`,
  versioniert) und die Rückgabe des Worker-Orchestrators prüfen.
- Der `maintenance-orchestrator` schreibt `status.json` bereits per `maintenance-check.py --done <aufgabe>`
  fort — keine Handarbeit an `status.json` nötig.
- Vorschläge in `docs/ai/tasks.md`/`questions.md` einarbeiten, `docs/ai/ledger.md` ergänzen (Skill
  `/commit`).
