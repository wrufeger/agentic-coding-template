# {{PROJEKTNAME}} — Vorlage für „Agentic Coding"

> Diese README richtet sich an Menschen (keine Vorkenntnisse über KI-Assistenten nötig). Platzhalter wie
> `{{PROJEKTNAME}}`, `{{AUFTRAGGEBER}}`, `{{ORCHESTRATOR}}` werden beim Anlegen des Projekts aus `CONFIG.md`
> ersetzt (Checkliste „Neues Projekt" in `docs/ai/checklists.md`, Claude Code: `/new-project`).

## Was ist das?

Ein Vorlagen-Repository für Projekte, an denen ein Mensch (**{{AUFTRAGGEBER}}**) zusammen mit einem oder
mehreren KI-Assistenten arbeitet — egal ob Claude Code, ChatGPT/Codex, GitHub Copilot, Cursor, Aider, Gemini
CLI oder ein lokales Modell. Es liefert:

- eine anbieterneutrale Regeldatei (`AGENTS.md`) plus Verweisdateien für die gängigen Werkzeuge,
- einen Arbeitsordner für die Zusammenarbeit (`docs/ai/`: Board, Aufgaben, Fragen, Ledger, Checklisten),
- ein Skelett für die eigentliche Projekt-Dokumentation (`docs/project/`),
- für Claude-Code-Nutzer zusätzlich fertige Sub-Agenten und Skills (`.claude/`), die dieselben Checklisten
  automatisiert anstoßen.

Der Kerngedanke: **ein Assistent orchestriert** (plant, prüft, committet), **weitere Assistenten/Sessions
arbeiten** die umrissenen Teilaufgaben ab. Details dazu in `AGENTS.md`.

## Schnellstart — zwei Wege

**Weg 1 — Neues Projekt**
1. Dieses Repository klonen: `git clone <Template-URL> <projekt>` — Projekt und Template teilen damit eine
   gemeinsame Git-Historie (Voraussetzung für spätere Updates per Merge). Danach
   `cd <projekt> && git remote rename origin template && git remote add origin <eigene-Repo-URL>`.
2. `CONFIG.md` im Repo-Root ausfüllen — oder leer lassen: dann entsteht ein leeres Projekt „MyApp", es wird
   nichts entfernt.
3. Assistenten anweisen: „Führe die Checkliste Neues Projekt aus (`docs/ai/checklists.md`)."
   Claude Code: `/new-project`.
4. Ergebnis: Platzhalter sind ersetzt, `docs/project/*` ist (bei ausgefüllter `CONFIG.md`) mit den Angaben
   befüllt, nicht genutzte Werkzeug-Dateien sind entfernt, `.claude/template.json` hält Basis-Commit und Werte
   fest — `CONFIG.md` ist danach weg.

**Weg 2 — Bestehendes Projekt nachrüsten**
1. Aus diesem Template-Checkout heraus: `python .claude/scripts/consume-template.py --target <ziel-repo>` —
   kopiert `AGENTS.md`, die Werkzeug-Verweisdateien, `.claude/`, `docs/ai/`, die `docs/project/`-Skelette und
   `CONFIG.md` in das bestehende Repo, ohne dort etwas zu überschreiben (Ausnahmen wie `README.md`/
   `.gitignore` werden als „von Hand zusammenführen" gemeldet).
2. Im Ziel-Repo Assistenten anweisen: „Führe die Checkliste Projekt nachrüsten aus (`docs/ai/checklists.md`)."
   Claude Code: `/consume-template`. Der Assistent analysiert den IST-Zustand und befüllt `CONFIG.md`
   sowie `docs/project/*` entsprechend (den Remote `template` hat Schritt 1 bereits angelegt).
3. Zum Schluss `python .claude/scripts/template-update.py --graft` — verknüpft die Historie mit dem Template
   (leerer Merge-Commit, Arbeitsbaum bleibt unverändert), damit spätere `/template-update`-Läufe funktionieren.

## Template später aktualisieren

Ein `SessionStart`-Hook meldet in Claude Code automatisch, wenn das Template neuer ist als der zuletzt
eingespielte Stand. Einspielen: Assistenten anweisen „Führe die Checkliste Template-Update aus"
(`docs/ai/checklists.md`), Claude Code: `/template-update`. Die in `.claude/template.json` unter
`keep_local` gelisteten Dateien (u. a. `docs/project/**`, `docs/ai/`-Arbeitsdateien, `README.md`,
`CONFIG.md`) gewinnen **bei Konflikten** immer mit der Projektfassung; `no_replace` listet zusätzlich
Dateien, die zwar normal mitgemergt, aber nie platzhalter-ersetzt werden (sie zeigen Platzhalter absichtlich
als Beispiel, u. a. `docs/ai/checklists.md`).

## Mit welchem Assistenten?

| Werkzeug | Liest automatisch | Start |
| :--- | :--- | :--- |
| Claude Code | `CLAUDE.md` + `AGENTS.md` (Verweis) | Repo öffnen, startet automatisch mit beiden Dateien |
| Codex/ChatGPT (Repo-Modus) | `AGENTS.md` | Repo öffnen, als Projektkontext erkannt |
| GitHub Copilot | `.github/copilot-instructions.md` | Repo öffnen, Copilot Chat nutzen |
| Cursor | `.cursor/rules/agents.mdc` (`alwaysApply: true`) | Repo öffnen, Regel lädt automatisch |
| Aider | `.aider.conf.yml` (lädt `AGENTS.md` + `board.md`) | `aider` im Repo-Root starten |
| Gemini CLI | `GEMINI.md` (Verweis) | `gemini` im Repo-Root starten |
| ChatGPT (Web), Ollama, sonstige | nichts automatisch | `AGENTS.md` + `docs/ai/board.md` als System-Prompt |

## Demo-Ablauf für einen Vortrag (ca. 15 Minuten)

Neutrale Arbeitsanweisung in Spalte 1 (funktioniert mit jedem Assistenten), Claude-Code-Kurzform in Spalte 2
(was das Publikum bei Claude Code zusätzlich sieht: Sub-Agenten, die parallel laufen).

| # | Schritt | Neutrale Anweisung | Claude Code | Was das Publikum sieht |
| :-- | :--- | :--- | :--- | :--- |
| 0 | Log-Fenster öffnen | `AI_LOG=ein` in `AGENTS.md`, zweites Terminal: `python .claude/scripts/ai-log.py --tail` | Hooks loggen automatisch | Live-Mitschnitt: Entscheidungen, Worker-Start/-Ende (`AGENTS.md` § Logging) |
| 1 | Neues Projekt | „Checkliste Neues Projekt ausführen." | `/new-project` | Platzhalter weg |
| 2 | Aufgabe anlegen | Aufgabe in `docs/ai/tasks.md` eintragen | — | Eine neue Zeile in `tasks.md` |
| 3 | Delegieren | „Checkliste Delegation ausführen, Aufgabe umsetzen." | `/delegate` | Sub-Agenten laufen parallel — im Log-Fenster als `[start]`/`[end]`-Zeilen |
| 4 | Prüfen | „Adversarialen Review der Änderung durchführen." | Sub-Agent `reviewer` | Kritischer Blick, Belege |
| 5 | Doku nachziehen | „Checkliste Doku-Nachzug ausführen." | `/project-docs` | `docs/project/*` aktualisiert sich |
| 6 | Abschließen | „Checkliste Sitzungsabschluss ausführen." | `/session-wrapup` | Neuer Ledger-Eintrag, Commit |
| 7 | Beleg zeigen | `git log -1 --stat` + Ledger-Eintrag zeigen | — | Nachvollziehbarer Beleg der Arbeit |

## Ordnerübersicht

```text
AGENTS.md            # anbieterneutrale Grundregeln (zuerst lesen)
CLAUDE.md             # Claude-Code-Ergänzung (Sub-Agenten, Skills, Modell-IDs)
CONFIG.md             # Formular für ein neues Projekt (Weg 1) — wird von /new-project gelesen und entfernt
GEMINI.md  .aider.conf.yml  .cursor/rules/agents.mdc  .github/copilot-instructions.md   # Werkzeug-Verweise
.claude/              # Claude Code: Sub-Agenten, Skills, Wartungs-Runner, Scripte, Settings (inkl. Logging-Hooks)
.claude/scripts/      # u. a. new-project.py, consume-template.py, template-update.py, ai-log.py
.claude/template.json # Herkunft/Update-Stand ggü. dem Template (Remote, Basis-Commit, eingesetzte Werte)
ai.log                # optionaler Live-Mitschnitt aller Agentenaktionen (gitignored, AGENTS.md § Logging)
docs/
  README.md           # Index aller Doku-Dateien
  project/            # Projekt-Doku (IST-Zustand): Architektur, Coding-Regeln, Tests, Features, ADRs, ...
  ai/                 # Zusammenarbeit: Board, Aufgaben, Fragen, Ledger, Umbauliste, Checklisten
.github/workflows/ci.yml   # Lint/Typecheck/Test (Platzhalter-Befehle)
.env.example  .mcp.json.example  renovate.json  .editorconfig  .gitignore  .gitattributes
```

## Modell-/Kostenlogik in Kürze

Ein starkes/teures Modell plant, integriert und prüft — die eigentliche Kleinarbeit übernehmen günstigere/
schnellere Modelle in klar umrissenen Teilaufgaben. Unabhängige Teilaufgaben laufen parallel, nicht
nacheinander. Ergebnisse werden vor der Übernahme stichprobenartig gegen den echten Stand geprüft, nie
blind übernommen. „Fertig" gilt nur mit einem Beleg (Testlauf, Commit-Hash, Aufruf von außen). Details und
eine Beispiel-Tabelle je Anbieter stehen in `AGENTS.md` § „Modell-/Kostenlogik".

## FAQ

**Muss ich Claude Code benutzen?** Nein. `AGENTS.md` ist die eigentliche Regeldatei und funktioniert mit jedem
Assistenten (siehe Tabelle oben); `.claude/` ist eine optionale, zusätzliche Automatisierungsschicht.

**Was gehört in `docs/ai/`, was in `docs/project/`?** `docs/ai/` ist Zusammenarbeit (Stand, Aufgaben, Fragen,
Verlauf) — `docs/project/` ist die eigentliche Projekt-Dokumentation (IST-Zustand von Architektur, Code, Tests).
Nie vermischen.

**Wer darf `docs/ai/` beschreiben?** Nur der Orchestrator (Hauptassistent). Sub-Agenten/Worker liefern
Ergebnisse zurück, schreiben dort aber nie hinein und committen nie (`AGENTS.md`).

**Was, wenn eine Aktion von einem Sicherheits-Classifier blockiert wird?** Siehe `AGENTS.md` §
„Umgang mit Sicherheits-/Safeguard-Warnungen" — nicht grundlos abbrechen, prüfen, ggf. eskalieren oder als
Aufgabe für {{AUFTRAGGEBER}} ablegen.

**Kann ich einzelne Dateien weglassen, die ich nicht brauche?** Ja — z. B. `.aider.conf.yml`, wenn Aider nicht
genutzt wird. `AGENTS.md`, `docs/ai/` und `docs/project/` sind der Kern und sollten bleiben.
