# Wartungslauf — Runner

Wiederkehrende Wartung für den Skill `/act-run-maintenance` (`.claude/skills/act-run-maintenance/SKILL.md`), fälligkeitsgesteuert
über `status.json`. **Optional:** per `AI-CONFIG.md` § „Wartung" abwählbar — bei „aus" entfernt `/act-create-project`
diesen Ordner, den Skill `/act-run-maintenance`, den Agenten `maintenance-orchestrator`, `maintenance-check.py` und den
zugehörigen `SessionStart`-Hook (siehe `.claude/scripts/create-project.py`).

## Dateien
- `status.json` — Aufgaben mit Intervall (Tage) und Datum des letzten/nächsten Laufs, siehe unten.
- `run-maintenance.ps1` — Windows-Variante, ruft Claude Code headless mit dem Skill auf.
- `run-maintenance.sh` — POSIX-Variante, gleiche Funktion.
- `reports/` — Berichte je Lauf (`YYYY-MM-DD.md`), **nur wenn `AI-CONFIG.md` → `Wartungsberichte`
  auf `intern` steht** — dann **gitignored** (siehe `.gitignore`). Der Default ist `docs`: Dann liegen die
  Berichte versioniert unter `docs/maintenance/` (im Doku-Index sichtbar, gleiches Schema), und
  `create-project.py --apply` legt dafür `docs/maintenance/README.md` an — dieser Ordner hier bleibt dann
  leer. Versioniert ist der Default, weil der Verlauf der Prüfungen sonst beim nächsten Checkout weg ist.
- `*.log` — Log-Dateien der Runner, **gitignored**.

## `status.json` — Schema und Fälligkeit
```json
{
  "aufgaben": {
    "kurz": { "intervall_tage": 14, "letzter_lauf": null, "naechster_lauf": null },
    "docs": { "intervall_tage": 30, "letzter_lauf": null, "naechster_lauf": null },
    "deps": { "intervall_tage": 90, "letzter_lauf": null, "naechster_lauf": null }
  },
  "_hinweis": "…"
}
```
- `intervall_tage: null` = **ereignisgesteuert** — die Aufgabe läuft nur auf Zuruf (`/act-run-maintenance <name>` bzw.
  `/act-run-maintenance alle`), nie automatisch fällig.
- Fehlt eine Aufgabe unter `aufgaben`, gilt sie als **deaktiviert**.
- Fällig ist eine Aufgabe, wenn `naechster_lauf` gesetzt und `<= heute` ist, oder wenn `intervall_tage` gesetzt
  und `letzter_lauf` noch `null` ist (noch nie gelaufen).
- Nach einem Lauf schreibt der `maintenance-orchestrator` (bzw. von Hand
  `maintenance-check.py --done <aufgabe>`) `letzter_lauf = heute` und `naechster_lauf = heute + intervall_tage`
  (bei `intervall_tage: null` nur `letzter_lauf`).
- Datumsformat immer `YYYY-MM-DD`.

## `maintenance-check.py`
Prüft/pflegt `status.json` (`.claude/scripts/maintenance-check.py`, Details im Kopfkommentar der Datei):
```
python .claude/scripts/maintenance-check.py --check [--quiet]   # faellige Aufgaben melden, Exit immer 0
python .claude/scripts/maintenance-check.py --list               # alle Aufgaben mit Status
python .claude/scripts/maintenance-check.py --status              # wie --list, plus Pfad/Einrichtungsstatus
python .claude/scripts/maintenance-check.py --done kurz,docs      # letzter_lauf/naechster_lauf fortschreiben
python .claude/scripts/maintenance-check.py --set docs=7,deps=0   # Intervalle setzen (0/leer/'-' = ereignisgesteuert)
```
`--check --quiet` läuft automatisch per `SessionStart`-Hook (`.claude/settings.json`) und meldet nur dann etwas,
wenn tatsächlich eine Aufgabe fällig ist — sonst keine Ausgabe, Exit-Code immer 0.

## Aufruf des Skills
```
pwsh -File .claude/maintenance/run-maintenance.ps1 [-Modus kurz|docs|deps|alle]
# oder
./.claude/maintenance/run-maintenance.sh [kurz|docs|deps|alle]
```
Ohne Argument: fälligkeitsgesteuert anhand `status.json` (nur was `maintenance-check.py --check` als fällig
meldet). Details zur Abarbeitung in `.claude/agents/maintenance-orchestrator.md`.

## Bericht-Schema
Jeder Lauf schreibt einen Bericht `YYYY-MM-DD.md` unter dem in `AI-CONFIG.md` → `Wartungsberichte`
gewählten Ordner (`.claude/maintenance/reports/`, gitignored — oder `docs/maintenance/`, versioniert) mit den
Abschnitten:
```
## Erledigt
## Abweichungen
## Vorschläge
## Belege
## Fehler/Abbrüche
```

## Einrichtung eines automatischen Laufs
Die Runner-Scripte selbst starten nichts von allein — sie müssen von einem Scheduler aufgerufen werden
(Windows Task Scheduler, `cron`, systemd-Timer o. ä.). Einrichtung ist eine Aufgabe für {{AUFTRAGGEBER}}
(Zugriff auf den Scheduler nötig) — siehe `docs/ai/tasks.md` § „Aufgaben nur für {{AUFTRAGGEBER}}".
