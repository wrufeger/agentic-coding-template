# {{PROJEKTNAME}} — Copilot-Ergänzung

Die Projektregeln stehen in [`AGENTS.md`](../AGENTS.md) (Repo-Root) — bitte zuerst lesen und befolgen. Diese
Datei ist nur ein Verweis für GitHub Copilot, keine eigene Regelquelle.

Zusätzlich vor Vorschlägen berücksichtigen: `docs/ai/board.md` (aktueller Stand), `docs/project/coding_rules.md`
(Stil- und Sprachregeln für dieses Projekt).

**Mehrere Agenten parallel:** Die Copilot CLI kennt dafür `/fleet <Auftrag>`; eigene Rollen liegen unter
`.github/agents/` und werden im Prompt per `@name` gerufen. Die Rollen dieses Projekts (Umsetzung, Recherche,
Review, Doku, Kurzcheck) stehen in `CLAUDE.md` § 1 — sie gelten inhaltlich auch hier, nur in Copilot-Syntax.
Was ein Worker darf und was nicht, steht in `AGENTS.md` § „Worker starten“.
