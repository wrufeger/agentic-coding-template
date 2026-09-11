---
name: project-docs
description: Checkliste Doku-Nachzug - docs/project/ nach jeder Feature-Welle nachziehen.
context: fork
agent: doc-writer
model: claude-sonnet-5
---

# Doku-Nachzug

Läuft als Fork im Sub-Agenten `doc-writer`: der Worker liest die geänderten Dateien/Commits dieser Sitzung,
setzt die werkzeugneutrale Checkliste „Doku-Nachzug" (`docs/ai/checklists.md`) um und meldet die geänderten
Doku-Abschnitte zurück. Der Hauptkontext prüft die Diffs, pflegt `docs/ai/` und committet
(Skill `session-wrapup`, nicht delegierbar).

## Auftrag an den Worker
- Übergib: was wurde gebaut/geändert (Stichpunkte, Commit-Bezug), welche Dateien unter `docs/project/`
  betroffen sein könnten.
- Der Worker arbeitet strikt nach `docs/ai/checklists.md` § „Doku-Nachzug" — kein Doku-Eintrag ohne Prüfung
  am Code, `docs/ai/` bleibt tabu.

## Nachlauf (Hauptkontext)
- `git diff --stat docs/project`, Stichproben der geänderten Abschnitte lesen.
- Vorschläge für `docs/ai/tasks.md`/`questions.md` einarbeiten, falls der Worker offene Punkte gemeldet hat.
