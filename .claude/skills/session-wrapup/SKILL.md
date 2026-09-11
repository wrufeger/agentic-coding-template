---
name: session-wrapup
description: Checkliste Sitzungsabschluss - Ledger, Aufgaben, Fragen, Doku-Index, Commit per Pathspec.
---

# Sitzungsabschluss (nur Hauptkontext)

Dieser Skill führt die werkzeugneutrale Checkliste „Sitzungsabschluss" aus `docs/ai/checklists.md` aus. Die
Checkliste selbst beschreibt die Schritte; hier steht nur die Claude-Code-Mechanik dazu.

## Ablauf

1. **Ledger-Entwurf auslagern:** einen Worker (`builder` oder ein frischer `general-purpose`-Agent mit Auftrag
   „nur Entwurf, nichts committen") den Ledger-Entwurf ins Scratchpad schreiben lassen (Stichpunkte + Belege
   aus dieser Sitzung als Prompt mitgeben); der Hauptkontext liest den Entwurf, prüft ihn gegen die
   tatsächlichen Belege und übernimmt ihn (gekürzt/korrigiert) in `docs/ai/`.
2. Ab hier wörtlich die Schritte 1–8 aus `docs/ai/checklists.md` § „Sitzungsabschluss" abarbeiten.
3. Attribution/Commit-Format wie in der aktuellen Session vorgegeben verwenden.
4. Bei eingeschaltetem Logging (`AGENTS.md` § Logging): nach dem Commit
   `python .claude/scripts/ai-log.py INFO orchestrator commit "<hash> <message>"`, als letzte Aktion
   `… INFO orchestrator session "ende · <Kurzbilanz>"` (`CLAUDE.md` § 7).

## Regeln
- Läuft **immer** im Hauptkontext, nie in einem Sub-Agenten — nur der Orchestrator schreibt in `docs/ai/`
  (`AGENTS.md`).
- Fremde uncommittete Änderungen anderer Sitzungen nicht stillschweigend mitnehmen — sichten, dann entscheiden.
