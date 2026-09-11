# {{PROJEKTNAME}} — Claude-Code-Ergänzung

Gilt **zusätzlich zu `AGENTS.md`** (zuerst lesen — dort stehen die werkzeugunabhängigen Grundregeln: Rollen,
`docs/ai/`, „Fertig nur mit Beleg", Commit per Pathspec, Safeguard-Verhalten, Doku-/Test-/Coding-Verweise,
Modell-/Kostenlogik). Diese Datei ergänzt nur, was für Claude Code spezifisch ist: Sub-Agenten, Skills,
`context: fork`, feste Modell-IDs, Token-Sparregeln, MCP-Hinweise, Memory. Platzhalter wie in `AGENTS.md`.

## 1. Sub-Agenten-Routing (`.claude/agents/`)

In der Rollensprache aus `AGENTS.md` ist {{ORCHESTRATOR}} der Orchestrator (Claude Code im Hauptfenster), die
folgenden Sub-Agenten sind die Worker:

- **[BUILD]** -> `.claude/agents/builder.md` (Umsetzung nach Auftrag: Code, Migration, Test, Konfiguration)
- **[EXPLORE]** -> `.claude/agents/explorer.md` (nur lesend: Codebase-/Doku-Recherche, Fundstellen `Datei:Zeile`)
- **[REVIEW]** -> `.claude/agents/reviewer.md` (adversarialer Review vor der Abnahme, Sicherheitsurteil, ALLOW/BLOCK)
- **[DOC-WRITE]** -> `.claude/agents/doc-writer.md` (Befunde in `docs/project/` einarbeiten; nie `docs/ai/`)
- **[QUICK-CHECK]** -> `.claude/agents/quick-check.md` (feste Lese-Kurzchecks ohne Bewertung)
- **[MAINTENANCE]** -> `.claude/agents/maintenance-orchestrator.md` (wiederkehrende Wartung nach
  `.claude/maintenance/status.json`)
- Mehrere unabhängige Prüfungen immer **parallel** starten (ein Nachrichtenblock, mehrere Agent-Aufrufe).
- Der Tabu-Bereich „Aufgaben nur für {{AUFTRAGGEBER}}" (`AGENTS.md`) gilt unverändert für jeden dieser Agenten.

## 2. Skills (`.claude/skills/`)

Jeder Skill ist die Claude-Code-Mechanik zu einer neutralen Checkliste aus `docs/ai/checklists.md` — die
Checkliste selbst beschreibt, WAS zu tun ist (werkzeugneutral), der Skill beschreibt, WIE Claude Code es startet.

| Skill | Checkliste in `docs/ai/checklists.md` | Mechanik |
| :--- | :--- | :--- |
| `/delegate` | „Delegation" | wann/wie an Sub-Agenten delegiert wird, Prompt-Schablone, Parallelstart |
| `/project-docs` | „Doku-Nachzug" | läuft als `context: fork` über `doc-writer` |
| `/new-idea` | „Idee → Projekt" | Interview → befüllt `project_description.md` + `architecture.md` |
| `/adapt-template` | „Template anpassen" | Platzhalter ersetzen, Stack-Regeln ergänzen |
| `/docs-audit` | „Doku-Audit" | `context: fork` über `maintenance-orchestrator`, Fan-out auf `doc-writer` |
| `/maintenance […]` | — (reine Automations-Mechanik) | `context: fork` über `maintenance-orchestrator` |
| `/session-wrapup` | „Sitzungsabschluss" | läuft **nie** in einem Sub-Agenten, nur im Hauptkontext |

## 3. Token-/Modellregeln

{{ORCHESTRATOR}}s eigenes Kontextbudget ist knapper als das der Sub-Agenten zusammen — Arbeit deshalb konsequent
in Sub-Agenten verlagern und den eigenen Kontext kleinhalten:

- {{ORCHESTRATOR}} liest keine Datei > 150 Zeilen komplett selbst — stattdessen `explorer` nutzen oder gezielt
  mit `grep -n`/`sed -n` ausschnittsweise lesen.
- Sub-Agenten immer mit **explizitem** `model`-Parameter starten (nie `inherit`/ohne Angabe): Haiku für reine
  Lese-/Zähl-/Existenzprüfungen, Sonnet für Tool-Ketten, Umsetzung und Doku-Edits, Opus nur für Review/
  Sicherheitsurteile. {{ORCHESTRATOR}} selbst bleibt bei Orchestrierung, Entscheidungen und `docs/ai/`.
- Rückgaben der Sub-Agenten ≤ 40 Zeilen (siehe „Rückgabe" je Agent), keine Rohdumps, Tabellen ≤ 15 Zeilen.
- Skills mit `context: fork` bevorzugen (Aufgabe läuft im Sub-Agenten, {{ORCHESTRATOR}} bekommt nur die Rückgabe).
- Ledger-Entwürfe von einem Sonnet-Agenten vorschreiben lassen (Checkliste „Sitzungsabschluss" § 0),
  {{ORCHESTRATOR}} prüft und übernimmt nur.
- **Script statt Sub-Agent:** Für komplexe, langwierige, token-intensive und wiederkehrende Vorgänge (Zählungen,
  Statusabfragen, Dateiübersichten, Datenstand-Prüfungen) beim ersten Mal ein Script unter `.claude/scripts/`
  anlegen (Stdlib, keine Secrets im Klartext, Kopfkommentar mit Zweck/Aufruf/Ausgabeformat) und danach nur noch
  ausführen — der Sub-Agent wertet dann nur die Script-Ausgabe aus. Eintrag in `.claude/scripts/README.md`.
  `maintenance-orchestrator` prüft regelmäßig, welche Agentenläufe scriptfähig sind.

Modell-Zuordnung je Agent (feste IDs, kein `inherit`; entspricht der Beispiel-Tabelle in `AGENTS.md` §
„Modell-/Kostenlogik", hier verbindlich für Claude Code):

| Agent | Modell | Grund | Umfang |
| :--- | :--- | :--- | :--- |
| `quick-check` | Haiku `claude-haiku-4-5-20251001` | Lese-/Zählprüfung ohne Urteil | Sekunden, ≤ 20 Zeilen |
| `builder` | Sonnet `claude-sonnet-5` | Umsetzung, Tool-Ketten, Tests als Beleg | eine umrissene Aufgabe |
| `explorer` | Sonnet `claude-sonnet-5` | Mehrdatei-Recherche mit Belegen | ein Recherche-Auftrag |
| `doc-writer` | Sonnet `claude-sonnet-5` | Stilurteil über mehrere Doku-Dateien | mehrere Dateien je Lauf |
| `maintenance-orchestrator` | Sonnet `claude-sonnet-5` | orchestriert Sub-Agenten | ganzer Wartungslauf |
| `reviewer` | Opus `claude-opus-5` | adversarialer Review, Sicherheitsurteil | isolierte Einzelfälle |

## 4. MCP-Server

`.mcp.json` (aus `.mcp.json.example`) bindet projektspezifische MCP-Server ein (z. B. Datenbank-, Deployment-
oder Ticket-Zugriff). Secrets nie in `.mcp.json` selbst, sondern per `${VAR}`-Referenz aus `.env`/der lokalen
Claude-Config; `.mcp.json` bleibt gitignored, sobald echte Werte eingetragen sind.

## 5. Memory

Nicht aus dem Repo ableitbares Wissen (Zugänge, Arbeitsweisen einzelner Personen, Umgebungsbesonderheiten) gehört
ins Claude-Memory, nicht in dieses Repo. Repo-Inhalte (Architektur, Entscheidungen, Stand) gehören nach
`docs/project/`/`docs/ai/` und werden dort gepflegt, nicht im Memory dupliziert.

## 6. Projektstruktur

```text
.
├── AGENTS.md                     # anbieterneutrale Grundregeln (zuerst lesen)
├── CLAUDE.md                     # diese Datei — Claude-Code-Ergänzung
├── GEMINI.md  .aider.conf.yml    # Verweise auf AGENTS.md für weitere Werkzeuge
├── .claude/
│   ├── agents/                  # builder, explorer, reviewer, doc-writer, quick-check, maintenance-orch.
│   ├── skills/                  # delegate, project-docs, new-idea, adapt-template, docs-audit, maintenance,
│   │                            # session-wrapup
│   ├── maintenance/              # Runner + Status für wiederkehrende Wartung, Logs gitignored
│   ├── scripts/                  # Scripte statt Sub-Agent für wiederkehrende Vorgänge
│   ├── settings.json              # geteilte, unkritische Permissions (keine Secrets)
│   └── settings.local.json.example
├── .cursor/rules/agents.mdc      # Verweis auf AGENTS.md für Cursor
├── .github/copilot-instructions.md  # Verweis auf AGENTS.md für Copilot
├── .github/workflows/ci.yml      # Lint/Typecheck/Test als Platzhalter-Steps
├── .env.example  .mcp.json.example  renovate.json  .editorconfig  .gitignore
└── docs/
    ├── README.md                 # Index-Tabelle: Datei · Inhalt · Datenstand · wann lesen
    ├── project/                  # Projekt-Doku (IST-Zustand), s. `AGENTS.md`
    └── ai/                       # Zusammenarbeit Mensch/KI (Board, Aufgaben, Fragen, Ledger, Checklisten)
```
