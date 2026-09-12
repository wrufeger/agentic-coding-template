# {{PROJEKTNAME}} — Gemini-CLI-Ergänzung

Die Projektregeln stehen in [`AGENTS.md`](./AGENTS.md) — bitte zuerst lesen und befolgen. Diese Datei ist nur
ein Verweis für Gemini CLI, keine eigene Regelquelle.

Zusätzlich vor der ersten Antwort lesen: `docs/ai/board.md` (aktueller Stand, nächster Schritt).

**Mehrere Agenten parallel:** Gemini CLI kennt Subagents — Verwaltung per `/agents`, Aufruf per `@name`,
Rollendateien unter `.gemini/agents/*.md`. Die Rollen dieses Projekts (Umsetzung, Recherche, Review, Doku,
Kurzcheck) stehen in `CLAUDE.md` § 1 und gelten inhaltlich auch hier. Was ein Worker darf und was nicht,
steht in `AGENTS.md` § „Worker starten“.
