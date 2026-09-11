---
name: new-idea
description: Checkliste Idee -> Projekt - Interview zu Ziel/Nutzern/Scope/Stack, befüllt project_description.md.
---

# Idee → Projekt

Setzt die werkzeugneutrale Checkliste „Idee → Projekt" aus `docs/ai/checklists.md` um. Läuft im Hauptkontext
(kein Fork), da es um Interview und Entscheidungen mit {{AUFTRAGGEBER}} geht.

## Ablauf
1. Interview führen: Ziel, Nutzer/Zielgruppe, Scope/Non-Scope, gewünschter Stack, bekannte Risiken. Bei
   Unklarheit fragen statt anzunehmen.
2. `docs/project/project_description.md` und `docs/project/architecture.md` befüllen (Skelett-Fragen dort
   ersetzen die offenen Punkte).
3. Erste Aufgaben in `docs/ai/tasks.md`, offene Entscheidungen in `docs/ai/questions.md` anlegen.
4. `docs/ai/board.md` aktualisieren.
5. Wenn der Stack feststeht: Skill `/adapt-template` anstoßen (Platzhalter, `coding_rules.md` § Stack-
   spezifisch, CI-Befehle).
