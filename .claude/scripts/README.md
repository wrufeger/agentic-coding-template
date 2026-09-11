# Scripte für wiederkehrende, token-intensive Vorgänge

Regel (`CLAUDE.md` § 3): Was komplex, langwierig und wiederkehrend ist, wird einmal als Script gebaut und
danach nur noch ausgeführt — der Sub-Agent wertet nur die Ausgabe aus. Stdlib bevorzugt, Secrets nur aus
`.env`/der lokalen Umgebung (nie hart codiert, nie in der Ausgabe), Kopfkommentar mit Zweck/Aufruf/
Ausgabeformat.

| Script | Zweck | Aufruf | Stand |
| :--- | :--- | :--- | :--- |
| `ai-log.py` | Agenten-Protokoll `ai.log` schreiben/mitlesen (`AGENTS.md` § Logging); Hook-Modus für Claude Code, CLI-Modus für jeden Assistenten mit Shell | `python .claude/scripts/ai-log.py <LEVEL> <agent> <topic> "<Text>"` · `--status` · `--tail [--grep X] [--lines N] [--no-color]` · `--reset` · `--hook` (nur aus `settings.json`) · Env `AI_LOG_RAW=1` (Diagnose, unmaskiert) | 2026-09-11 |

**Kandidaten (beim nächsten Wartungslauf prüfen):** Dateiübersicht `docs/project/` (Pfad · Zeilen · Datenstand)
für `docs/README.md`, Zählung offener Aufgaben/Fragen, Abhängigkeits-Report-Zusammenfassung.
