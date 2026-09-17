Steuerung der Zusammenarbeit mit KI-Assistenten in diesem Projekt. Die Datei bleibt dauerhaft im Repo und
wirkt **laufend**: Der Orchestrator liest sie vor jeder Aufgabe und setzt um, was sich seit dem letzten
Abgleich geändert hat — sie ist Steuerung, kein Protokoll.

**Bearbeitet wird nur die Spalte „Wert".** Dort steht bereits der Standard; wer ihn behalten will, lässt die
Zelle stehen. Eine geleerte Zelle bedeutet dasselbe wie der Standard. Die Spalte „Optionen" ist nur bei
Feldern mit fester Auswahl gefüllt, bei Freitext bleibt sie leer. Stehen die Optionen mit **Komma**, sind sie
gleichrangig — eine davon gilt. Stehen sie mit **`<`**, sind es Stufen: jede schließt die links davon ein,
`unit < integration` heißt also „Integration bringt die Unit-Tests mit". „Platzhalter" nennt die Marke, die der
Wert im ganzen Repo ersetzt; im Repo steht sie in doppelten geschweiften Klammern, hier ohne, damit sie beim
Anlegen nicht selbst ersetzt wird. Bleibt die Wert-Zelle leer, bleibt auch die Marke stehen.

Umgesetzt wird mit `python .claude/scripts/sync-config.py --check` (zeigt, was offen ist) und `--apply`.
Ergänzungen laufen dabei durch: ein nachgetragenes KI-Werkzeug holt sich seine Dateien aus dem Template, ein
ergänzter Regelsatz kommt dazu. Alles, was löscht oder projektweit ersetzt — ein gestrichenes Werkzeug, ein
geänderter Rufname —, wird vorher gezeigt und braucht eine Zusage.

Ausführliche Begründungen zu einzelnen Schlüsseln (nicht nur die kurze Spalte „Bedeutung"): `docs/ai/config-guide.md`.

## Projekt

| Schlüssel | Wert | Optionen | Platzhalter | Bedeutung |
| :--- | :--- | :--- | :--- | :--- |
| Projektname | MyApp |  | `PROJEKTNAME` | Name des Projekts. |
| Auftraggeber | Entwickler |  | `AUFTRAGGEBER` | Der Mensch, der Ziele setzt, Fragen beantwortet und freigibt. |
| Orchestrator |  |  | `ORCHESTRATOR` | Rufname des Haupt-Assistenten. Leer = Kurzname dessen, was arbeitet: bei Claude Code das gewählte Modell (Opus, Sonnet, Haiku), sonst das Werkzeug (Gemini, Codex, Cursor, …). Wird keines erkannt, gilt „Fable“. Er hört unabhängig davon immer auch auf „Orchestrator“ und auf direkte Anrede. |
| Sprache | Deutsch |  |  | Sprache der Doku. Nur Hinweis beim Befüllen, keine Marke im Repo. |

## Technik

| Schlüssel | Wert | Optionen | Platzhalter | Bedeutung |
| :--- | :--- | :--- | :--- | :--- |
| Stack |  |  | `STACK` | Sprachen, Frameworks, Datenbank — ein Satz reicht. |
| Coding-Guidelines |  | bash, csharp, go, java, nuxt, php, python, sql, tailwind, typescript, vue |  | Kommaliste der Regelsätze, die das Projekt übernimmt. |
| Install-Befehl |  |  | `INSTALL_BEFEHL` | Steht in `ci.yml` und `setup.md`. |
| Dev-Start-Befehl |  |  | `DEV_START_BEFEHL` | Steht in `setup.md`. |
| Lint-Befehl |  |  | `LINT_BEFEHL` | Steht in `ci.yml` und `testing.md`. |
| Typecheck-Befehl |  |  | `TYPECHECK_BEFEHL` | Steht in `ci.yml` und `testing.md`. |
| Test-Befehl |  |  | `TEST_BEFEHL` | Steht in `ci.yml` und `testing.md`. |
| E2E-Befehl |  |  | `E2E_BEFEHL` | Steht in `testing.md` und `setup.md`. |
| Testtiefe | alles | ohne < unit < integration < e2e < alles |  | Wie weit getestet wird (nicht, ob getestet werden darf). Jede Stufe schließt die kleineren ein. |

Regelsätze lassen sich jederzeit nachladen: Kennung hier ergänzen, oder direkt
`python .claude/scripts/guidelines.py --add <kennung>`.

## Assistenten

| Schlüssel | Wert | Optionen | Platzhalter | Bedeutung |
| :--- | :--- | :--- | :--- | :--- |
| KI-Werkzeuge |  | Claude Code, Copilot, Cursor, Aider, Gemini CLI, ChatGPT/Codex, Ollama, Cline |  | Kommaliste der Werkzeuge, die **bleiben** sollen. Leer = alle behalten. |
| Orchestrator-Modell | opus | opus, sonnet, haiku, inherit |  | Modell der Hauptsession, steuert `model` in `.claude/settings.json`. |
| Commit-Verhalten | automatisch | automatisch, fragen, manuell |  | Wie der Orchestrator mit der Checkliste „Aufgabe abschließen" umgeht. |
| Ideen-Ablauf | automatisch | automatisch, konzept, direkt |  | Was mit einer Idee oder einem Änderungswunsch passiert, bevor gebaut wird. |
| Schreibstil | kurz | kurz, normal, ausführlich |  | Wie ausführlich Fragen, Aufgaben, Journal und Antworten formuliert werden. |
| Feedback | aus | aus, bestaetigen, automatisch, manuell |  | Freiwillige Rückmeldung an den Template-Autor — ob und wie **von selbst** gesendet wird. Eine von Hand geschriebene Nachricht (`/act-feedback <Text>`) geht immer, auch bei `aus`. |
| Feedback-Takt | woechentlich | manuell, sofort, stuendlich, taeglich, woechentlich, adaptiv, automatisch |  | Wie oft höchstens gesendet wird. Wirkt nur, wenn `Feedback` nicht `aus` oder `manuell` ist. `adaptiv` richtet sich danach, wie oft am Projekt gearbeitet wird. |
| Feedback-Umfang | a,b,c | a, b, c (Kommaliste) |  | Was der Assistent **von sich aus** sammeln darf: `a` Kennzahlen aus `git log`/Dateisystem, `b` Änderungen an KI-Regeln und Doku-Struktur (als Beschreibung), `c` Werkzeug-Nutzung. Leer = nur Registrierung und selbst geschriebenes Feedback. |
| Code-Optimierung | aus | aus, ein, intensiv |  | Politur frisch geschriebenen Codes auf Kürze und Lesbarkeit. |
| Globale Ablage | nein | nein, agenten, agenten+skills, alles, fragen |  | Legt Rollen und allgemeine Skills zusätzlich nach `~/.claude/`, für alle Projekte dieses Rechners. |
| MCP-Server |  | figma, playwright, chrome-devtools, github, grafana, home-assistant, ha-mcp, sentry, linear, notion, slack, atlassian, context7, postgres, mysql-mariadb, filesystem, fetch, adobe-firefly, openai-image, replicate-flux, fal-ai, google-imagen |  | Kommaliste der MCP-Server, die dieses Projekt nutzt. Katalog: `.claude/mcp-katalog.md`. Eingerichtet wird von Hand. Leer = keiner. |

Begründungen zu diesen Schlüsseln (Modell, Commit-Verhalten, Ideen-Ablauf, Schreibstil, Feedback samt Umfang
und Takt, Code-Optimierung, MCP-Server, globale Ablage): `docs/ai/config-guide.md` § „Assistenten".

## Protokoll und Wartung

| Schlüssel | Wert | Optionen | Platzhalter | Bedeutung |
| :--- | :--- | :--- | :--- | :--- |
| Logging | aus | aus, ein |  | Mitschnitt aller Agentenaktionen in `ai.log`; steuert `AI_LOG` in `AGENTS.md`. |
| Logging-Tiefe | INFO | ERROR < WARN < INFO < DEBUG |  | Steuert `AI_LOG_LEVEL` in `AGENTS.md`: geschrieben wird alles ab dieser Stufe. |
| Wartung | aus | aus, ein |  | Wiederkehrende Wartung. `aus` entfernt Ordner, Skill, Agent und Fälligkeits-Hook — **umkehrbar**: `ein` holt sie aus dem Template-Remote zurück (Ablauf: `docs/ai/config-guide.md`). |
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
