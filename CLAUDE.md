# {{PROJEKTNAME}} — Claude-Code-Ergänzung

Gilt **zusätzlich zu `AGENTS.md`** (zuerst lesen — dort stehen die werkzeugunabhängigen Grundregeln: Rollen,
`docs/ai/`, „Fertig nur mit Beleg", Commit per Pathspec, Safeguard-Verhalten, Doku-/Test-/Coding-Verweise,
Modell-/Kostenlogik). Diese Datei ergänzt nur, was für Claude Code spezifisch ist: Sub-Agenten, Skills,
`context: fork`, feste Modell-IDs, Token-Sparregeln, MCP-Hinweise, Memory, Logging-Hooks. Platzhalter wie in
`AGENTS.md`.

## 1. Sub-Agenten-Routing (`.claude/agents/`)

In der Rollensprache aus `AGENTS.md` ist {{ORCHESTRATOR}} der Orchestrator (Claude Code im Hauptfenster), die
folgenden Sub-Agenten sind die Worker:

- **[BUILD]** -> `.claude/agents/builder.md` (Umsetzung nach Auftrag: Code, Migration, Test, Konfiguration)
- **[EXPLORE]** -> `.claude/agents/explorer.md` (nur lesend: Codebase-/Doku-Recherche, Fundstellen `Datei:Zeile`)
- **[REVIEW]** -> `.claude/agents/reviewer.md` (adversarialer Review vor der Abnahme, Sicherheitsurteil, ALLOW/BLOCK)
- **[DOC-WRITE]** -> `.claude/agents/doc-writer.md` (Befunde in `docs/project/` einarbeiten; nie `docs/ai/`)
- **[QUICK-CHECK]** -> `.claude/agents/quick-check.md` (feste Lese-Kurzchecks ohne Bewertung)
- **[MAINTENANCE]** -> `.claude/agents/maintenance-orchestrator.md` (wiederkehrende Wartung nach
  `.claude/maintenance/status.json`; optional — per `CONFIG.md` § `Wartung` abwählbar)
- **[EXPERT]** -> `.claude/agents/expert-solver.md` (Eskalation, Fable 5.1 mit hoher Denkstufe — **nur**, wenn
  ein Worker zweimal an derselben Aufgabe gescheitert ist oder ein Fehler unlösbar erscheint)
- Mehrere unabhängige Prüfungen immer **parallel** starten (ein Nachrichtenblock, mehrere Agent-Aufrufe).
- Der Tabu-Bereich „Aufgaben nur für {{AUFTRAGGEBER}}" (`AGENTS.md`) gilt unverändert für jeden dieser Agenten.

**Eskalation statt Wiederholung:** Scheitert ein Worker zweimal an derselben Aufgabe, wird der Auftrag kein
drittes Mal gestellt. Lag es am Auftrag, wird er geschärft und einmal neu gestartet; sonst übernimmt
`expert-solver` mit vollständigem Kontext (ursprünglicher Auftrag, beide Fehlversuche samt Ausgaben, betroffene
Dateien, bereits ausgeschlossene Ursachen). Sein Befund wird verbucht — Ledger, bei einer wiederverwendbaren
Lehre zusätzlich `docs/project/coding_rules.md` oder `docs/ai/backlog.md`.

## 2. Skills (`.claude/skills/`)

Jeder Skill ist die Claude-Code-Mechanik zu einer neutralen Checkliste aus `docs/ai/checklists.md` — die
Checkliste selbst beschreibt, WAS zu tun ist (werkzeugneutral), der Skill beschreibt, WIE Claude Code es startet.

| Skill | Checkliste in `docs/ai/checklists.md` | Mechanik |
| :--- | :--- | :--- |
| `/delegate` | „Delegation" | wann/wie an Sub-Agenten delegiert wird, Prompt-Schablone, Parallelstart |
| `/project-docs` | „Doku-Nachzug" | läuft als `context: fork` über `doc-writer` |
| `/new-project` | „Neues Projekt" | `CONFIG.md` einlesen → Platzhalter/Werkzeugdateien/Logging setzen, Doku befüllen; Mechanik in `.claude/scripts/new-project.py`, läuft **nie** in einem Sub-Agenten |
| `/consume-template` | „Projekt nachrüsten" | läuft im Ziel-Repo, nach `consume-template.py`; Fan-out auf `explorer`/`doc-writer` |
| `/docs-audit` | „Doku-Audit" | `context: fork` über `general-purpose`, Fan-out auf `explorer`/`doc-writer` (bewusst unabhängig von der optionalen Wartung) |
| `/maintenance […]` | — (reine Automations-Mechanik) | `context: fork` über `maintenance-orchestrator`; **optional** — steht in `CONFIG.md` `Wartung: aus`, entfernt `/new-project` diesen Skill samt Agent, Ordner und Fälligkeits-Hook |
| `/template-update` | „Template-Update" | läuft **nie** in einem Sub-Agenten, nur im Hauptkontext; Mechanik in `.claude/scripts/template-update.py` |
| `/session-wrapup` | „Sitzungsabschluss" | läuft **nie** in einem Sub-Agenten, nur im Hauptkontext |

## 3. Token-/Modellregeln

{{ORCHESTRATOR}}s eigenes Kontextbudget ist knapper als das der Sub-Agenten zusammen — Arbeit deshalb konsequent
in Sub-Agenten verlagern und den eigenen Kontext kleinhalten:

- {{ORCHESTRATOR}} liest keine Datei > 150 Zeilen komplett selbst — stattdessen `explorer` nutzen oder gezielt
  mit `grep -n`/`sed -n` ausschnittsweise lesen.
- {{ORCHESTRATOR}} selbst läuft auf **Opus** — festgelegt über `"model": "opus"` in `.claude/settings.json`,
  damit jede Sitzung im Projekt gleich startet (überschreibbar per `/model`, `--model` oder `ANTHROPIC_MODEL`;
  beim Anlegen des Projekts wählbar über `CONFIG.md` § `Orchestrator-Modell`). Der Kopf plant, prüft und
  entscheidet — gespart wird bei den Workern, nicht hier.
- Sub-Agenten immer mit **explizitem** `model`-Parameter starten (nie `inherit`/ohne Angabe): Haiku für reine
  Lese-/Zähl-/Existenzprüfungen, Sonnet für Tool-Ketten, Umsetzung und Doku-Edits, Opus nur für Review/
  Sicherheitsurteile, Fable 5.1 nur für die Eskalation. {{ORCHESTRATOR}} selbst bleibt bei Orchestrierung,
  Entscheidungen und `docs/ai/`.
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
| {{ORCHESTRATOR}} (Hauptsession) | Opus `opus` (`settings.json`) | plant, prüft, entscheidet, committet | ganze Sitzung |
| `quick-check` | Haiku `claude-haiku-4-5-20251001` | Lese-/Zählprüfung ohne Urteil | Sekunden, ≤ 20 Zeilen |
| `builder` | Sonnet `claude-sonnet-5` | Umsetzung, Tool-Ketten, Tests als Beleg | eine umrissene Aufgabe |
| `explorer` | Sonnet `claude-sonnet-5` | Mehrdatei-Recherche mit Belegen | ein Recherche-Auftrag |
| `doc-writer` | Sonnet `claude-sonnet-5` | Stilurteil über mehrere Doku-Dateien | mehrere Dateien je Lauf |
| `maintenance-orchestrator` | Sonnet `claude-sonnet-5` | orchestriert Sub-Agenten | ganzer Wartungslauf |
| `reviewer` | Opus `claude-opus-5` | adversarialer Review, Sicherheitsurteil | isolierte Einzelfälle |
| `expert-solver` | Fable 5.1 `claude-fable-5-1`, `effort: high` | Eskalation nach zwei Fehlversuchen | ein festgefahrener Fall |

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
├── CONFIG.md                     # Formular für ein neues Projekt (Weg 1), von /new-project gelesen+entfernt
├── GEMINI.md  .aider.conf.yml    # Verweise auf AGENTS.md für weitere Werkzeuge
├── .claude/
│   ├── agents/                  # builder, explorer, reviewer, doc-writer, quick-check, expert-solver,
│   │                            # maintenance-orchestrator (optional)
│   ├── skills/                  # delegate, project-docs, new-project, consume-template, docs-audit,
│   │                            # maintenance, template-update, session-wrapup
│   ├── maintenance/              # optional: Status/Intervalle + Runner für wiederkehrende Wartung
│   ├── scripts/                  # Scripte statt Sub-Agent für wiederkehrende Vorgänge, ai-log.py (Logging),
│   │                            # template-update.py (Template-Updates per Merge, --graft), new-project.py
│   │                            # (Weg 1), consume-template.py (Weg 2, läuft aus dem Template-Checkout),
│   │                            # maintenance-check.py (Fälligkeit der Wartung, SessionStart-Hook)
│   ├── template.json              # Herkunft/Update-Stand ggü. dem Template (Remote, Basis-Commit, Werte)
│   ├── settings.json              # Modell der Hauptsession, unkritische Permissions (keine Secrets), Hooks
│   └── settings.local.json.example
├── .cursor/rules/agents.mdc      # Verweis auf AGENTS.md für Cursor
├── .github/copilot-instructions.md  # Verweis auf AGENTS.md für Copilot
├── .github/workflows/ci.yml      # Lint/Typecheck/Test als Platzhalter-Steps
├── .env.example  .mcp.json.example  renovate.json  .editorconfig  .gitignore  .gitattributes
├── ai.log                        # optionaler Live-Mitschnitt (gitignored), Schalter in AGENTS.md § Logging
└── docs/
    ├── README.md                 # Index-Tabelle: Datei · Inhalt · Datenstand · wann lesen
    ├── project/                  # Projekt-Doku (IST-Zustand), s. `AGENTS.md`
    └── ai/                       # Zusammenarbeit Mensch/KI (Board, Aufgaben, Fragen, Ledger, Checklisten)
```

## 7. Logging (Claude-Code-Mechanik zu `AGENTS.md` § Logging)

Schalter (`AI_LOG`, `AI_LOG_LEVEL`), Format und Themenliste stehen in `AGENTS.md` § Logging — dort wird
umgeschaltet, nicht hier. Claude Code liefert dazu zwei Schreibwege in dieselbe `ai.log`:

- **Automatisch per Hooks** (`.claude/settings.json` → `hooks`, `shell: bash`; Agent-Aufruf und
  Sub-Agent-Start/-Ende laufen synchron mit Timeout 10 s, damit die Nummernvergabe in Startreihenfolge bleibt,
  alle übrigen Events `async`; bei `AI_LOG=aus` sofortiges No-op): `python .claude/scripts/ai-log.py --hook`
  erzeugt `[user] [prompt]` bei jeder Eingabe, `[<aufrufer>] [delegate]` bei jedem Agent-Aufruf (Sub-Agent,
  Auftrag, Modell; Aufrufer ist meist `orchestrator`, bei verschachtelten Aufrufen der Sub-Agent), `[<agent>#<n>] [start]` und
  `[end]` für jeden Sub-Agenten, `[session] start/ende`, `[error]` bei fehlgeschlagenen Tools und
  `wartet auf Freigabe` bei Permission-Prompts. Auf `DEBUG` zusätzlich jeder Tool-Aufruf — auch innerhalb von
  Sub-Agenten, per `agent_id` dem Verursacher zugeordnet — und die gekürzten Rückgaben der Sub-Agenten.
  **Nummerierung:** jeder Sub-Agent bekommt beim `SubagentStart` eine laufende Nummer je Sitzung und Typ
  (`builder#1`, `builder#2`, …; Zuordnung `agent_id → Name` in `ai.log.state.json`, gitignored). Der Auftrag
  in der `[start]`-Zeile stammt aus dem zeitlich passenden Agent-Aufruf (Reihenfolge je Typ) — bei mehreren
  gleichzeitig gestarteten Agenten desselben Typs ist das eine Zuordnung nach Startreihenfolge, keine
  Garantie. Zur Kontrolle der echten Hook-Felder einmal mit `AI_LOG_RAW=1` starten: dann landet jede
  Hook-Payload zusätzlich als JSON-Zeile in `ai.log.raw.jsonl` (gitignored, danach löschen).
- **Von Hand (Pflicht bei `ein`)** für das, was kein Hook sehen kann — die Überlegungen des Orchestrators und
  die Meilensteine der Worker. {{ORCHESTRATOR}} schreibt **vor** jeder Welle die Entscheidung, nach jedem Commit
  den Hash, beim Abschluss die Bilanz; Sub-Agenten schreiben unter ihrem Namen (`[test]`, `[result]`,
  `[review]`, `[docs]`), ≤ 5 Zeilen je Lauf (Regel steht in jeder Agenten-Definition). Startet
  {{ORCHESTRATOR}} mehrere Sub-Agenten desselben Typs in einer Welle, nennt er jedem im Prompt seinen Log-Namen
  in Startreihenfolge („Dein Log-Name: `builder#2`") — `--status` zeigt die zuletzt vergebenen Nummern:

  ```text
  python .claude/scripts/ai-log.py INFO orchestrator decision "#12 in 3 Teile: explorer (Bestand), 2× builder parallel (Form, Tests)"
  python .claude/scripts/ai-log.py INFO orchestrator commit "3f9c2ab feat: Login-Formular mit Validierung"
  python .claude/scripts/ai-log.py INFO orchestrator session "ende · 1 Feature, 2 Commits, 1 offene Frage (#7)"
  ```

  Ein Aufruf je Zeile, kein Roh-Dump, keine Secrets; die Permission dafür ist in `settings.json` freigegeben.
- **Vortrag:** zweites Terminal mit `python .claude/scripts/ai-log.py --tail` (farbig, `--grep builder` für
  einen Worker), Level `INFO`; vorher `--reset` (alte Datei wird zu `ai.log.<zeitstempel>.bak`); `--status`
  zeigt, ob der Schalter greift und woher der Wert stammt (`AGENTS.md`, `env`).
- **Voraussetzung/Abschalten:** Python 3 im PATH (Windows: Git Bash + Python; der Hook nimmt `python3`, sonst
  `python` — in den Beispielen hier steht `python`, auf macOS/Linux `python3`). `AI_LOG=aus` genügt zum
  Abschalten; wer die Hooks ganz los sein will, entfernt den `hooks`-Block aus `settings.json`. Das Log ist
  Mitschnitt, kein Beleg — Belege bleiben Testlauf, Commit-Hash, Ledger.
