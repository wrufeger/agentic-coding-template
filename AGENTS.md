# AGENTS.md — anbieterneutrale Regeln für {{PROJEKTNAME}}

> Platzhalter (`{{PROJEKTNAME}}`, `{{AUFTRAGGEBER}}`, `{{ORCHESTRATOR}}`, `{{STACK}}`) werden beim Anpassen des
> Templates ersetzt (Checkliste „Template anpassen" in `docs/ai/checklists.md`).

Diese Datei gilt für **jeden** KI-Assistenten, der an diesem Projekt arbeitet — unabhängig vom Werkzeug: Claude
Code, ChatGPT/Codex, GitHub Copilot, Cursor, Aider, Gemini CLI, ein lokales Modell über Ollama oder ein anderer
Agent. Sie beschreibt die werkzeugunabhängigen Grundregeln. Werkzeug-spezifische Ergänzungen (Sub-Agent-
Definitionen, feste Modell-IDs, Automations-Mechanik) stehen in eigenen Dateien und verweisen hierher zurück:
`CLAUDE.md` (Claude Code), `.cursor/rules/agents.mdc` (Cursor), `.github/copilot-instructions.md` (Copilot),
`.aider.conf.yml` (Aider), `GEMINI.md` (Gemini CLI). Für ChatGPT/Ollama/andere: Inhalt dieser Datei plus
`docs/ai/board.md` von Hand als System-Prompt laden (siehe `README.md` § „Mit welchem Assistenten?").

## Platzhalter

| Platzhalter | Bedeutung | Beispiel |
| :--- | :--- | :--- |
| `{{PROJEKTNAME}}` | Name des Projekts | „Beispiel-App" |
| `{{AUFTRAGGEBER}}` | Mensch, der das Projekt verantwortet und entscheidet | „Wolfgang" |
| `{{ORCHESTRATOR}}` | Rufname des jeweils genutzten Haupt-Assistenten | „Fable" |
| `{{STACK}}` | Technologie-Stack in Kurzform | „Nuxt 4 + MariaDB" |

## Rollen

- **Orchestrator** — der jeweils genutzte Haupt-Assistent (Claude Code im Hauptfenster, ein ChatGPT-/Codex-Chat,
  die Cursor-Chatsession, die Aider-Hauptsession, …). Plant, entscheidet, integriert, prüft und committet. Nur
  der Orchestrator schreibt in `docs/ai/`.
- **Worker** — Sub-Agenten, zweite Sessions oder spezialisierte Modelle, die der Orchestrator beauftragt (z. B.
  Claude-Sub-Agenten, eine zweite Codex-/Cursor-Instanz, ein separater Ollama-Lauf). Arbeiten nach einem klar
  umrissenen Auftrag mit Kontext, Liefergegenstand und Format, liefern Ergebnis **plus Beleg** zurück. Ein Worker
  committet **nie** und schreibt **nie** in `docs/ai/`.
- **Auftraggeber** — {{AUFTRAGGEBER}}, der Mensch, der Ziele setzt, Fragen beantwortet und kritische Schritte
  freigibt.

## Grundregeln

- Arbeitsordner `docs/ai/`: Board, Aufgaben, Fragen, Ledger, Umbauliste, Checklisten — Aufbau und Formregeln in
  `docs/ai/README.md`.
- „Fertig" gilt nur mit Beleg: Testlauf, Commit-Hash oder ein Aufruf von außen, der das Ergebnis zeigt.
- Commits ausschließlich per Pathspec (nie ein catch-all wie `git add -A`/`git add .`), kurze Commit-Messages im
  bisherigen Stil des Repos.
- Nur der Orchestrator schreibt in `docs/ai/` und committet. Worker liefern Ergebnis und Beleg an den
  Orchestrator zurück, ändern `docs/ai/` nie und committen nie.
- Menschlicher Originaltext in `docs/ai/` (Fragen, Antworten, Kommentare von {{AUFTRAGGEBER}}) ist unantastbar:
  nie editieren oder löschen, nur darunter kommentieren.
- **Tabu-Bereich:** Der Abschnitt „Aufgaben nur für {{AUFTRAGGEBER}}" in `docs/ai/tasks.md` wird von keinem
  Assistenten (Orchestrator oder Worker) je ausgeführt — dort stehen Dinge, die fehlende Rechte, ein
  Produktionsrisiko oder eine Entscheidung betreffen, die nur ein Mensch treffen darf (Zugangsdaten anlegen,
  Produktions-Deployments, endgültiges Löschen, Rechte-/Kontenänderungen). Einträge dort dürfen ergänzt,
  präzisiert oder als erledigt markiert werden, sobald {{AUFTRAGGEBER}} es meldet.

## Umgang mit Sicherheits-/Safeguard-Warnungen

Manche Werkzeuge markieren Anfragen oder Aktionen intern als riskant (Guardrails, Content-Filter,
Berechtigungs-Eskalation). Regel für jeden Assistenten:

1. Nicht grundlos abbrechen. Zuerst prüfen, ob die Warnung ein Fehlalarm bezüglich dieses konkreten Projekt-
   Kontexts ist.
2. Ist sie berechtigt: prüfen, ob eine genauer begründete, kleinteiligere oder „harmlosere" Formulierung den
   eigentlichen Arbeitskern erreicht, ohne den Auslöser zu berühren.
3. Bleibt die Aufgabe wichtig und geflaggt: an ein stärkeres/anders eingestuftes Modell delegieren (Rolle
   „Review"), statt den ganzen Orchestrator-Kontext dauerhaft umzustellen.
4. Bleibt sie geflaggt und betrifft sie den Tabu-Bereich (siehe oben): als Aufgabe mit Rezept (Kontext + genauer
   Schritt) unter „Aufgaben nur für {{AUFTRAGGEBER}}" ablegen statt zu erzwingen.

## Doku, Tests, Coding

- Projekt-Doku (IST-Zustand) liegt in `docs/project/`: `architecture.md` (Aufbau, Datenfluss), `coding_rules.md`
  (Stil- und Sprachregeln), `testing.md` (Testpyramide, Pflichtläufe, ungetestete Bereiche), `features.md`
  (Featureliste mit Status), `decisions.md` (Architekturentscheidungen/ADRs), `incidents/README.md`
  (Schema für schwere Fehleranalysen).
- Vor Code-Änderungen `docs/project/coding_rules.md` lesen; vor neuen Features/Schnittstellen `features.md` und
  `decisions.md`, damit keine bereits getroffene Entscheidung stillschweigend revidiert wird.
- Lint, Typecheck und Unit-Tests laufen vor jedem Commit und in der CI (`.github/workflows/ci.yml`);
  Integrations-/E2E-Tests bei größeren oder UI-relevanten Änderungen. Details: `docs/project/testing.md`.
- Diese Datei nur anfassen, wenn sich eine werkzeugunabhängige Grundregel ändert — Stack-Details gehören nach
  `docs/project/coding_rules.md`, werkzeugspezifische Mechanik in die jeweilige Ergänzungsdatei.

## Modell-/Kostenlogik (anbieterneutral)

Grundprinzip unabhängig vom Anbieter: das teure/starke Modell **plant, integriert und prüft**, ein günstigeres/
schnelleres Modell **arbeitet** die umrissenen Teilaufgaben ab. Unabhängige Teilaufgaben parallel starten;
Ergebnisse der Worker stichprobenartig gegen den tatsächlichen Code/Stand verifizieren, bevor sie in Board,
Doku oder Commit übernommen werden.

| Rolle | Zweck | Anthropic | OpenAI | Google | lokal (Ollama) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| Orchestrator/Review | planen, prüfen, Sicherheitsurteil | Opus | GPT-5-Pro/o-Serie | Gemini 2.x Pro | größtes Modell |
| Standard-Arbeit | Umsetzung, Tool-Ketten, Doku | Sonnet | GPT-5 | Gemini 2.x Flash | mittleres Modell (30–70B) |
| Kurzcheck | Lese-/Zähl-/Existenzprüfung | Haiku | GPT-5-mini/nano | Gemini Flash-Lite | kleines Modell (3–8B) |

Diese Zuordnung ist ein Beispiel, keine Pflicht — welches Modell welche Rolle übernimmt, richtet sich nach dem
Werkzeug, das gerade genutzt wird (siehe die werkzeugspezifischen Dateien für feste IDs, sofern das Werkzeug das
unterstützt).

## Werkzeugspezifische Ergänzungsdateien

| Werkzeug | Datei | Inhalt |
| :--- | :--- | :--- |
| Claude Code | `CLAUDE.md` | Sub-Agenten, Skills, feste Modell-IDs, Token-Sparregeln, MCP |
| GitHub Copilot | `.github/copilot-instructions.md` | Verweis auf diese Datei |
| Cursor | `.cursor/rules/agents.mdc` | Verweis auf diese Datei, `alwaysApply: true` |
| Aider | `.aider.conf.yml` | lädt diese Datei plus `docs/ai/board.md` automatisch |
| Gemini CLI | `GEMINI.md` | Verweis auf diese Datei |
| ChatGPT/Codex, Ollama, sonstige | — | Inhalt dieser Datei + `docs/ai/board.md` manuell laden |
