# {{PROJEKTNAME}} — Vorlage für „Agentic Coding"

> Diese README richtet sich an Menschen (keine Vorkenntnisse über KI-Assistenten nötig). Platzhalter wie
> `{{PROJEKTNAME}}`, `{{AUFTRAGGEBER}}`, `{{ORCHESTRATOR}}` werden beim Anpassen des Templates ersetzt
> (Checkliste „Template anpassen" in `docs/ai/checklists.md`).

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

## Schnellstart — drei Wege

**A — eigenes Projekt aus dem Template**
1. Dieses Repository kopieren/als Vorlage nutzen, in ein neues Repo umziehen.
2. Assistenten anweisen: „Führe die Checkliste Template anpassen aus (`docs/ai/checklists.md`)."
   Claude Code: `/adapt-template`.
3. Platzhalter sind ersetzt, `docs/project/coding_rules.md` § Stack-spezifisch ist ausgefüllt, CI-Befehle
   stehen — weiter mit Weg C, Schritt 3.

**B — neue Idee → Projekt**
1. Template wie in A übernehmen.
2. Assistenten anweisen: „Führe die Checkliste Idee → Projekt aus (`docs/ai/checklists.md`)."
   Claude Code: `/new-idea`.
3. Der Assistent führt ein kurzes Interview (Ziel, Nutzer, Scope, Stack, Risiken) und befüllt
   `docs/project/project_description.md`, `architecture.md` sowie erste Einträge in `docs/ai/tasks.md`.
4. Weiter mit Weg A, Schritt 2 (Template anpassen), sobald der Stack feststeht.

**C — bestehendes Repo nachrüsten**
1. Aus diesem Template `AGENTS.md`, die Werkzeug-Verweisdateien (`CLAUDE.md`, `GEMINI.md`, `.aider.conf.yml`,
   `.cursor/rules/agents.mdc`, `.github/copilot-instructions.md`), `docs/ai/` und die `docs/project/`-Skelette
   in das bestehende Repo kopieren.
2. Skelette mit dem echten IST-Zustand befüllen (nicht raten — am Code prüfen).
3. Ersten Eintrag in `docs/ai/board.md` und `docs/ai/ledger.md` schreiben, danach normal weiterarbeiten.

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
| 1 | Template übernehmen | „Checkliste Template anpassen ausführen." | `/adapt-template` | Platzhalter weg |
| 2 | Aufgabe anlegen | Aufgabe in `docs/ai/tasks.md` eintragen | — | Eine neue Zeile in `tasks.md` |
| 3 | Delegieren | „Checkliste Delegation ausführen, Aufgabe umsetzen." | `/delegate` | Sub-Agenten laufen parallel |
| 4 | Prüfen | „Adversarialen Review der Änderung durchführen." | Sub-Agent `reviewer` | Kritischer Blick, Belege |
| 5 | Doku nachziehen | „Checkliste Doku-Nachzug ausführen." | `/project-docs` | `docs/project/*` aktualisiert sich |
| 6 | Abschließen | „Checkliste Sitzungsabschluss ausführen." | `/session-wrapup` | Neuer Ledger-Eintrag, Commit |
| 7 | Beleg zeigen | `git log -1 --stat` + Ledger-Eintrag zeigen | — | Nachvollziehbarer Beleg der Arbeit |

## Ordnerübersicht

```text
AGENTS.md            # anbieterneutrale Grundregeln (zuerst lesen)
CLAUDE.md             # Claude-Code-Ergänzung (Sub-Agenten, Skills, Modell-IDs)
GEMINI.md  .aider.conf.yml  .cursor/rules/agents.mdc  .github/copilot-instructions.md   # Werkzeug-Verweise
.claude/              # Claude Code: Sub-Agenten, Skills, Wartungs-Runner, Scripte, Settings
docs/
  README.md           # Index aller Doku-Dateien
  project/            # Projekt-Doku (IST-Zustand): Architektur, Coding-Regeln, Tests, Features, ADRs, ...
  ai/                 # Zusammenarbeit: Board, Aufgaben, Fragen, Ledger, Umbauliste, Checklisten
.github/workflows/ci.yml   # Lint/Typecheck/Test (Platzhalter-Befehle)
.env.example  .mcp.json.example  renovate.json  .editorconfig  .gitignore
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
