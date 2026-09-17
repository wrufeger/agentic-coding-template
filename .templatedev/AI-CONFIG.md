Steuerung der Zusammenarbeit mit KI-Assistenten in diesem Projekt. Die Datei bleibt dauerhaft im Repo und
beschreibt den Stand der Pflege-Sitzung für die Weiterentwicklung des Agentic-Coding-Templates im
Elternordner (`..`).

## Projekt

| Schlüssel | Wert | Optionen | Platzhalter | Bedeutung |
| :--- | :--- | :--- | :--- | :--- |
| Projektname | Template-Pflege |  | `PROJEKTNAME` | Name des Projekts. |
| Auftraggeber | Wolfgang |  | `AUFTRAGGEBER` | Der Mensch, der Ziele setzt, Fragen beantwortet und freigibt. |
| Orchestrator | Opus |  | `ORCHESTRATOR` | Rufname des Haupt-Assistenten. |

Ziel: Weiterentwicklung des Agentic-Coding-Templates im Elternordner — Befunde aus Testprojekten bewerten,
Regeln/Scripte/Skills ändern und dort belegen.

## Technik

| Schlüssel | Wert | Optionen | Platzhalter | Bedeutung |
| :--- | :--- | :--- | :--- | :--- |
| Stack | Python 3 + Markdown (Agentic-Coding-Template) |  | `STACK` | Sprachen, Frameworks, Datenbank. |
| Coding-Guidelines | python |  |  | Kommaliste der Regelsätze, die das Projekt übernimmt. |
| Install-Befehl | — |  | `INSTALL_BEFEHL` | Kein Install-Schritt nötig (reine Stdlib-Scripte). |
| Dev-Start-Befehl | — |  | `DEV_START_BEFEHL` | Kein Dev-Server. |
| Lint-Befehl | `python -m py_compile ../.claude/scripts/*.py scripts/*.py` |  | `LINT_BEFEHL` | Syntaxprüfung der Scripte. |
| Typecheck-Befehl | — |  | `TYPECHECK_BEFEHL` | Kein Typecheck. |
| Test-Befehl | `python ../.claude/scripts/check-refs.py --root .. --check && python ../.claude/scripts/check-refs.py --root . --check` |  | `TEST_BEFEHL` | Verweisprüfung Root-Template und `.templatedev/` selbst. |
| E2E-Befehl | — |  | `E2E_BEFEHL` | Kein E2E. |
| Testtiefe | unit |  | | Nur Verweisprüfung/Scriptläufe, keine eigene Anwendung. |

## Assistenten

| Schlüssel | Wert | Optionen | Platzhalter | Bedeutung |
| :--- | :--- | :--- | :--- | :--- |
| KI-Werkzeuge | Claude Code |  |  | Kommaliste der Werkzeuge, die bleiben sollen. |
| Orchestrator-Modell | opus | opus, sonnet, haiku, inherit |  | Modell der Hauptsession, steuert `model` in `.claude/settings.json`. |
| Commit-Verhalten | automatisch | automatisch, fragen, manuell |  | Wie der Orchestrator mit der Checkliste „Aufgabe abschließen" umgeht. |
| Ideen-Ablauf | automatisch | automatisch, konzept, direkt |  | Was mit einer Idee passiert, bevor gebaut wird. |
| Schreibstil | kurz | kurz, normal, ausführlich |  | Wie ausführlich Fragen, Aufgaben, Journal formuliert werden. |
| Feedback | aus | aus, bestaetigen, automatisch, manuell |  | Freiwillige Rückmeldung an den Template-Autor — hier aus, weil dieses Projekt selbst der Template-Autor ist. |
| Feedback-Takt | woechentlich | manuell, sofort, stuendlich, taeglich, woechentlich, adaptiv, automatisch |  | Wirkt nur, wenn `Feedback` nicht `aus`. |
| Feedback-Umfang | a,b,c | a, b, c (Kommaliste) |  | Ohne Wirkung bei `Feedback: aus`. |
| Code-Optimierung | aus | aus, ein, intensiv |  | Politur frisch geschriebenen Codes — hier aus. |
| Globale Ablage | nein | nein, agenten, agenten+skills, alles, fragen |  | Keine projektübergreifende Ablage nach `~/.claude/`. |
| MCP-Server |  |  |  | Keine MCP-Server in dieser Sitzung. |

## Protokoll und Wartung

| Schlüssel | Wert | Optionen | Platzhalter | Bedeutung |
| :--- | :--- | :--- | :--- | :--- |
| Logging | aus | aus, ein |  | Mitschnitt aller Agentenaktionen in `ai.log`. |
| Logging-Tiefe | INFO | ERROR < WARN < INFO < DEBUG |  | Ohne Wirkung bei `Logging: aus`. |
| Wartung | aus | aus, ein |  | Wiederkehrende Wartung — hier aus, kein Wartungsordner/-skill/-hook. |

Nicht in der Tabelle, weil niemand ihn setzt: `DATUM` wird bei jedem Doku-Lauf mit dem Tagesdatum gefüllt.

Einstellungen hier werden nicht per `sync-config.py` umgesetzt (im Pflege-Projekt gesperrt); sie
dokumentieren den Stand.

## Ziel

Die Arbeit am Agentic-Coding-Template folgt denselben KI-Regeln und derselben Ordnerstruktur wie ein per
`/act-create-project` angelegtes Projekt (Board, Aufgaben, Fragen, Ledger, Backlog, Doku), statt eigener
Sonderformen im ehemals unstrukturierten `.templatedev/`.

## Nutzer

Wolfgang, als Auftraggeber und alleiniger Pfleger des Templates.

## Features

- Struktur wie ein reguläres Projekt (`docs/ai/`, `docs/project/`), Formregeln für Fragen/Aufgaben gelten
  auch hier.
- Gesperrte Einrichtungs-Skills (`act-create-project`, `act-apply-template`, `act-finalize`,
  `act-run-maintenance`, `act-feedback`), weil sie hier nie Sinn ergeben.
- `act-process-feedback` läuft ausschließlich hier.

## Non-Scope

Kein eigener Produktcode, keine Anwendung, kein Deployment — reine Pflege des Templates im Elternordner.

## Architektur

Siehe `docs/project/concepts/project-structure.md`.

## Risiken

Platzhalter-Ersetzung darf nie in den Root-Template-Ordner (`../docs/`, `../AGENTS.md`, `../CLAUDE.md`)
zurückwirken — diese bleiben Formular ohne echte Werte.

## Sonstiges

—
