---
name: delegate
description: Checkliste Delegation - wann/wie an Sub-Agenten delegiert wird, Prompt-Schablone, Parallelstart.
---

# Delegation — Power-Modus in Claude Code

Setzt die werkzeugneutrale Checkliste „Delegation" aus `docs/ai/checklists.md` um. Dort steht das WAS
(wann/warum delegieren), hier steht das WIE in Claude Code.

## Sub-Agenten (`.claude/agents/`)

- `explorer` (Sonnet, nur lesend) — Codebase-Analyse mit `Datei:Zeile`-Report.
- `builder` (Sonnet) — setzt einen umrissenen Auftrag um, liefert Lint/Typecheck/Test-Beleg, committet nie.
- `reviewer` (Opus) — adversarialer Review vor dem Commit, fixt echte Fehler, belegt am Code/Laufzeittest;
  auch für Guardrail-Bewertungen (`AGENTS.md` § Safeguard-Verhalten).
- `doc-writer` (Sonnet) — pflegt `docs/project/`, nie `docs/ai/`.
- `quick-check` (Haiku) — feste Lese-Kurzchecks ohne Bewertung.

Aufruf über das Agent-Tool mit `subagent_type` gleich dem Agentennamen und **explizitem** `model` (siehe
`CLAUDE.md` § Token-/Modellregeln).

## Mechanik

- Unabhängige Worker immer in **einem** Nachrichtenblock mit mehreren Agent-Aufrufen starten (echte
  Parallelität), nie nacheinander, wenn sie voneinander unabhängig sind.
- Skills mit `context: fork` bevorzugen, wenn eine ganze Aufgabe (nicht nur ein Teilschritt) in einem
  Sub-Agenten laufen soll — der Hauptkontext bekommt dann nur die Rückgabe.
- Jeder Auftrag: Kontext (2–3 Sätze), konkreter Liefergegenstand, Format des Ergebnisses, was zu ignorieren ist.

Restliche Regeln (Auftrags-Schablone, Abschluss-Disziplin, wann nicht delegieren) stehen unverändert in
`docs/ai/checklists.md` § „Delegation".
