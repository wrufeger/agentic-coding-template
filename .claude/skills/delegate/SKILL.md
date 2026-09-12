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
- `expert-solver` (Fable 5.1, `effort: high`) — High-Reasoning-Eskalation, nur nach zweimaligem Scheitern
  desselben Auftrags oder bei einem unlösbaren Edge-Case aufrufen, nicht für normale Arbeit.

Aufruf über das Agent-Tool mit `subagent_type` gleich dem Agentennamen und **explizitem** `model` (siehe
`CLAUDE.md` § Token-/Modellregeln).

## Mechanik

- Unabhängige Worker immer in **einem** Nachrichtenblock mit mehreren Agent-Aufrufen starten (echte
  Parallelität), nie nacheinander, wenn sie voneinander unabhängig sind.
- Skills mit `context: fork` bevorzugen, wenn eine ganze Aufgabe (nicht nur ein Teilschritt) in einem
  Sub-Agenten laufen soll — der Hauptkontext bekommt dann nur die Rückgabe.
- Jeder Auftrag: Kontext (2–3 Sätze), konkreter Liefergegenstand, Format des Ergebnisses, was zu ignorieren ist.
- Bei eingeschaltetem Logging (`AGENTS.md` § Logging): **vor** dem Start der Welle die Entscheidung schreiben —
  `python .claude/scripts/ai-log.py INFO orchestrator decision "<Aufteilung, Modellwahl, warum>"`. Die
  `[delegate]`-, `[start]`- und `[end]`-Zeilen der Sub-Agenten erzeugen die Hooks von selbst (`CLAUDE.md` § 7).
  Mehrere Sub-Agenten desselben Typs in einer Welle: jedem im Prompt seinen Log-Namen nennen (`builder#1`,
  `builder#2`, … in der Reihenfolge der Agent-Aufrufe; nächste freie Nummer zeigt `ai-log.py --status`).

## Eskalation

Scheitert ein Worker an derselben Aufgabe **zweimal**, wird nicht ein drittes Mal derselbe Auftrag gestellt:

- (a) Lag der Fehler erkennbar am Auftrag (unklar, unvollständig, falsche Annahme), den Auftrag schärfen und
  **einmal** neu starten — mit demselben oder einem anderen Standard-Worker.
- (b) Sonst `expert-solver` mit dem vollständigen Kontext starten: ursprünglicher Auftrag, beide Fehlversuche
  (was wurde versucht, welche Ausgabe kam zurück), betroffene Dateien, bereits ausgeschlossene Ursachen.
- (c) Den Befund von `expert-solver` verbuchen (`docs/ai/ledger.md`, ggf. `docs/project/coding_rules.md`/
  `docs/ai/backlog.md`).

Merksatz: Eskalation ist billiger als die dritte Wiederholung.

Restliche Regeln (Auftrags-Schablone, Abschluss-Disziplin, wann nicht delegieren) stehen unverändert in
`docs/ai/checklists.md` § „Delegation".
