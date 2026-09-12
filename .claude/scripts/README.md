# Scripte für wiederkehrende, token-intensive Vorgänge

Regel (`CLAUDE.md` § 3): Was komplex, langwierig und wiederkehrend ist, wird einmal als Script gebaut und
danach nur noch ausgeführt — der Sub-Agent wertet nur die Ausgabe aus. Stdlib bevorzugt, Secrets nur aus
`.env`/der lokalen Umgebung (nie hart codiert, nie in der Ausgabe), Kopfkommentar mit Zweck/Aufruf/
Ausgabeformat.

| Script | Zweck | Aufruf | Stand |
| :--- | :--- | :--- | :--- |
| `ai-log.py` | Agenten-Protokoll `ai.log` schreiben/mitlesen (`AGENTS.md` § Logging); Hook-Modus für Claude Code, CLI-Modus für jeden Assistenten mit Shell | `python .claude/scripts/ai-log.py <LEVEL> <agent> <topic> "<Text>"` · `--status` · `--tail [--grep X] [--lines N] [--no-color]` · `--reset` · `--hook` (nur aus `settings.json`) · Env `AI_LOG_RAW=1` (Diagnose, unmaskiert) | 2026-09-11 |
| `template-update.py` | Template-Updates per Git-Merge einspielen (`.claude/template.json`), Platzhalterwerte bleiben erhalten; `--check` läuft zusätzlich automatisch per `SessionStart`-Hook; `--graft` verknüpft nachgerüstete Projekte (kein gemeinsamer Vorfahr) per leerem Merge mit dem Template | `python .claude/scripts/template-update.py --init [--url U] [--base H] [--set K=V ...]` · `--set K=V ...` · `--check [--quiet]` · `--apply [--commit]` · `--continue [--commit]` · `--abort` · `--status` · `--graft` | 2026-09-11 |
| `new-project.py` | Weg 1 „Neues Projekt": `CONFIG.md` einlesen, Platzhalter ersetzen, nicht genutzte Werkzeug-Dateien entfernen, `AI_LOG`/`AI_LOG_LEVEL` setzen, Werte in `.claude/template.json` schreiben | `python .claude/scripts/new-project.py --dry-run` (Default) · `--apply` · `--finish` | 2026-09-11 |
| `consume-template.py` | Weg 2 „Projekt nachrüsten": kopiert die Agentic-Coding-Grundausstattung aus diesem Template-Checkout in ein bestehendes Repo, ohne dort etwas zu überschreiben; schreibt `.claude/template.json` im Ziel und legt den Remote `template` an | `python .claude/scripts/consume-template.py --target <ziel-repo> [--dry-run]` (läuft aus dem Template-Checkout heraus) | 2026-09-11 |
| `maintenance-check.py` | Fälligkeit der wiederkehrenden Wartung (`.claude/maintenance/status.json`) prüfen/pflegen; `--check --quiet` läuft zusätzlich automatisch per `SessionStart`-Hook (meldet nur bei Fälligkeit, Exit immer 0). Optional — existiert nur, wenn `CONFIG.md` § „Wartung" auf „ein" steht | `python .claude/scripts/maintenance-check.py --check [--quiet]` (Default) · `--list` · `--status` · `--done <aufgabe>[,...]\|alle [--date YYYY-MM-DD]` · `--set <aufgabe>=<tage>[,...]` | 2026-09-12 |

**Kandidaten (beim nächsten Wartungslauf prüfen):** Dateiübersicht `docs/project/` (Pfad · Zeilen · Datenstand)
für `docs/README.md`, Zählung offener Aufgaben/Fragen, Abhängigkeits-Report-Zusammenfassung.
