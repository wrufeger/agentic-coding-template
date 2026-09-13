Steuerung der Zusammenarbeit mit KI-Assistenten in diesem Projekt. Die Datei bleibt dauerhaft im Repo und
wirkt **laufend**: Der Orchestrator liest sie vor jeder Aufgabe und setzt um, was sich seit dem letzten
Abgleich geändert hat — sie ist Steuerung, kein Protokoll.

**Bearbeitet wird nur die Spalte „Wert".** Dort steht bereits der Standard; wer ihn behalten will, lässt die
Zelle stehen. Eine geleerte Zelle bedeutet dasselbe wie der Standard. Die Spalte „Optionen" ist nur bei
Feldern mit fester Auswahl gefüllt, bei Freitext bleibt sie leer. „Platzhalter" nennt die Marke, die der
Wert im ganzen Repo ersetzt; im Repo steht sie in doppelten geschweiften Klammern, hier ohne, damit sie beim
Anlegen nicht selbst ersetzt wird. Bleibt die Wert-Zelle leer, bleibt auch die Marke stehen.

Umgesetzt wird mit `python .claude/scripts/sync-config.py --check` (zeigt, was offen ist) und `--apply`.
Ergänzungen laufen dabei durch: ein nachgetragenes KI-Werkzeug holt sich seine Dateien aus dem Template, ein
ergänzter Regelsatz kommt dazu. Alles, was löscht oder projektweit ersetzt — ein gestrichenes Werkzeug, ein
geänderter Rufname —, wird vorher gezeigt und braucht eine Zusage.

## Projekt

| Schlüssel | Wert | Optionen | Platzhalter | Bedeutung |
| :--- | :--- | :--- | :--- | :--- |
| Projektname | MyApp |  | `PROJEKTNAME` | Name des Projekts. |
| Auftraggeber | Entwickler |  | `AUFTRAGGEBER` | Der Mensch, der Ziele setzt, Fragen beantwortet und freigibt. |
| Orchestrator | Fable |  | `ORCHESTRATOR` | Rufname des Haupt-Assistenten. |
| Sprache | Deutsch |  |  | Sprache der Doku. Nur Hinweis beim Befüllen, keine Marke im Repo. |

## Technik

| Schlüssel | Wert | Optionen | Platzhalter | Bedeutung |
| :--- | :--- | :--- | :--- | :--- |
| Stack |  |  | `STACK` | Sprachen, Frameworks, Datenbank — ein Satz reicht. |
| Coding-Guidelines |  | bash, csharp, go, nuxt, php, python, sql, tailwind, typescript, vue |  | Kommaliste der Regelsätze, die das Projekt übernimmt. |
| Install-Befehl |  |  | `INSTALL_BEFEHL` | Steht in `ci.yml` und `setup.md`. |
| Dev-Start-Befehl |  |  | `DEV_START_BEFEHL` | Steht in `setup.md`. |
| Lint-Befehl |  |  | `LINT_BEFEHL` | Steht in `ci.yml` und `testing.md`. |
| Typecheck-Befehl |  |  | `TYPECHECK_BEFEHL` | Steht in `ci.yml` und `testing.md`. |
| Test-Befehl |  |  | `TEST_BEFEHL` | Steht in `ci.yml` und `testing.md`. |
| E2E-Befehl |  |  | `E2E_BEFEHL` | Steht in `testing.md` und `setup.md`. |

Regelsätze lassen sich jederzeit nachladen: Kennung hier ergänzen, oder direkt
`python .claude/scripts/guidelines.py --add <kennung>`.

## Assistenten

| Schlüssel | Wert | Optionen | Platzhalter | Bedeutung |
| :--- | :--- | :--- | :--- | :--- |
| KI-Werkzeuge |  | Claude Code, Copilot, Cursor, Aider, Gemini CLI, ChatGPT/Codex, Ollama |  | Kommaliste der Werkzeuge, die **bleiben** sollen. Leer = alle behalten. |
| Orchestrator-Modell | opus | opus, sonnet, haiku, inherit |  | Modell der Hauptsession, steuert `model` in `.claude/settings.json`. |
| Commit-Verhalten | automatisch | automatisch, fragen, manuell |  | Wie der Orchestrator mit der Checkliste „Aufgabe abschließen" umgeht. |
| Code-Optimierung | aus | aus, ein, intensiv |  | Politur frisch geschriebenen Codes auf Kürze und Lesbarkeit. |
| Globale Ablage | nein | nein, agenten, agenten+skills, alles, fragen |  | Legt Rollen und allgemeine Skills zusätzlich nach `~/.claude/`, für alle Projekte dieses Rechners. |
| MCP-Server |  | figma, playwright, chrome-devtools, github, grafana, home-assistant, sentry, linear, notion, slack, atlassian, context7, postgres, mysql-mariadb, filesystem, fetch, adobe-firefly, openai-image, replicate-flux, fal-ai, google-imagen |  | Kommaliste der MCP-Server, die dieses Projekt nutzt. Katalog: `.claude/mcp-katalog.md`. Eingerichtet wird von Hand. Leer = keiner. |

Zum Modell: Der Orchestrator plant, prüft und entscheidet — gespart wird bei den Workern, nicht hier.
Zum Commit-Verhalten: `automatisch` committet abgenommene Arbeit selbst, `fragen` schlägt sie vor und wartet,
`manuell` wartet auf eine ausdrückliche Anweisung.
Zur Code-Optimierung: `ein` ist eine Runde, `intensiv` bis zu zwei und nimmt Geschwindigkeit und Speicher
dazu, `aus` entfernt den Agenten `optimizer`. Der ältere Wert `streng` gilt weiter und bedeutet `intensiv`.
Zu den MCP-Servern: Die Kennungen stehen mit Anbieter, Zweck, Reifegrad und benötigten Umgebungsvariablen
in `.claude/mcp-katalog.md`. Eingetragen werden nur Server, die das Projekt wirklich braucht — jeder weitere
ist eine zusätzliche Vertrauensbeziehung und bei den schreibfähigen zusätzlich ein Risiko. Secrets kommen nie
in `.mcp.json`, sondern als `${VAR}` aus der Prozessumgebung (`CLAUDE.md` § MCP-Server); für Schreibzugriffe
gilt `AGENTS.md` § „Zugriff auf laufende Systeme".
Zur globalen Ablage: Was dort liegt, sehen Team, CI und Sitzungen in der Cloud **nicht** — Verbindliches
gehört ins Repo. Mechanik: `python .claude/scripts/install-global.py --plan`.

## Protokoll und Wartung

| Schlüssel | Wert | Optionen | Platzhalter | Bedeutung |
| :--- | :--- | :--- | :--- | :--- |
| Logging | aus | aus, ein |  | Mitschnitt aller Agentenaktionen in `ai.log`; steuert `AI_LOG` in `AGENTS.md`. |
| Logging-Tiefe | INFO | DEBUG, INFO, WARN, ERROR |  | Steuert `AI_LOG_LEVEL` in `AGENTS.md`. |
| Wartung | aus | aus, ein |  | Wiederkehrende Wartung. `aus` entfernt Ordner, Skill, Agent und Fälligkeits-Hook. |
| Wartungsaufgaben | kurz=14, docs=30, deps=90 |  |  | Aufgabe=Intervall in Tagen; weggelassene Aufgabe wird abgeschaltet. Nur bei „Wartung: ein". |
| Wartungsberichte | docs | docs, intern |  | `docs` = `docs/maintenance/`, versioniert und im Doku-Index; `intern` = `.claude/maintenance/reports/`, gitignored. |

## Nur beim Nachrüsten eines bestehenden Projekts

| Schlüssel | Wert | Optionen | Platzhalter | Bedeutung |
| :--- | :--- | :--- | :--- | :--- |
| Code-Analyse | fragen | nein, vorschlagen, fragen |  | Nach der Doku zusätzlich den Bestand prüfen und Verbesserungen sammeln. |
| Struktur-Migration | fragen | ja, nein, fragen |  | Vorhandene KI-Arbeitsordner und Regeldateien auf die Template-Struktur umstellen. |
| Alter Orchestrator-Name |  |  |  | Bisheriger Rufname im Projekt; wird durch den Wert von `Orchestrator` ersetzt. Leer = das Script schlägt Kandidaten vor. |

Nicht in der Tabelle, weil niemand ihn setzt: `DATUM` wird beim Anlegen und bei jedem Doku-Lauf mit dem
Tagesdatum gefüllt.

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
