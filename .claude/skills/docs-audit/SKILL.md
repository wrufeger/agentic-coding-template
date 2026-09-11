---
name: docs-audit
description: Prüft docs/project/ gegen den Code-Zustand per Fan-out auf parallele Read-only-Worker, pflegt den Index.
context: fork
agent: maintenance-orchestrator
model: claude-sonnet-5
---

# Doku-Audit (parallel, read-only)

Läuft als Fork im Sub-Agenten `maintenance-orchestrator`: der Worker übernimmt Fan-out, Auswertung und
Index-Pflege; der Hauptkontext prüft danach die Diffs, pflegt `docs/ai/` (Board/Aufgaben/Fragen/Ledger) und
committet (Skill `/session-wrapup`, nicht delegierbar).

## Ablauf im Fork
1. `git status`/`git diff --stat docs`: offene Änderungen früherer Sitzungen sichten.
2. Fan-out: `explorer` ermittelt die Code-Realität (welche Module/Endpunkte/Tabellen existieren wirklich,
   `Datei:Zeile`-Belege), `doc-writer` gleicht `docs/project/*` dagegen ab und korrigiert direkt — beide
   gleichzeitig starten, falls unabhängig aufteilbar (z. B. je Doku-Bereich ein Paar).
3. `doc-writer` aktualisiert `docs/README.md` (Index, Datenstände).
4. Rückgabe an den Hauptkontext: Kurzfazit, Abweichungstabelle (≤ 15 Zeilen), geänderte Dateien nur als
   `Pfad · Abschnitt · 1 Zeile`, Vorschläge für `docs/ai/tasks.md`/`questions.md`.

## Abschluss (Hauptkontext, nicht delegierbar)
`git status`/`git diff --stat docs` gegenprüfen, Vorschläge in `docs/ai/tasks.md`/`questions.md` einarbeiten,
dann Skill `/session-wrapup`.

## Grenzen
Nichts wird am Code geändert; Findings, die Code-Änderungen brauchen, werden Aufgaben in `docs/ai/tasks.md`.
