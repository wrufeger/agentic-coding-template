# Wartungslauf — Runner

Headless-Runner für den Skill `/maintenance` (`.claude/skills/maintenance/SKILL.md`), z. B. für einen
Task-Scheduler/Cron-Job außerhalb einer interaktiven Claude-Code-Session.

## Dateien
- `status.json` — Datum des letzten Laufs je Aufgabe (`kurz`/`docs`/`deps`), `null` = noch nie gelaufen.
- `run-maintenance.ps1` — Windows-Variante, ruft Claude Code headless mit dem Skill auf.
- `run-maintenance.sh` — POSIX-Variante, gleiche Funktion.
- `reports/` — Berichte je Lauf (`YYYY-MM-DD.md`), **gitignored** (siehe `.gitignore`).
- `*.log` — Log-Dateien der Runner, **gitignored**.

## Aufruf
```
pwsh -File .claude/maintenance/run-maintenance.ps1 [-Modus kurz|docs|deps|alle]
# oder
./.claude/maintenance/run-maintenance.sh [kurz|docs|deps|alle]
```

Ohne Argument: fälligkeitsgesteuert anhand `status.json` (Details in
`.claude/agents/maintenance-orchestrator.md`).

## Einrichtung eines automatischen Laufs
Die Runner-Scripte selbst starten nichts von allein — sie müssen von einem Scheduler aufgerufen werden
(Windows Task Scheduler, `cron`, systemd-Timer o. ä.). Einrichtung ist eine Aufgabe für {{AUFTRAGGEBER}}
(Zugriff auf den Scheduler nötig) — siehe `docs/ai/tasks.md` § „Aufgaben nur für {{AUFTRAGGEBER}}".
