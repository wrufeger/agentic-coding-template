---
name: act-release
description: Release vorbereiten - Vorbedingungen prüfen, Version nach Semantic Versioning festlegen, lesbares Änderungsprotokoll aus den Commits erzeugen, Tag setzen. Auslöser - "/release", "Release vorbereiten", "neue Version veröffentlichen", "Changelog erstellen", "Tag setzen".
---

# Release vorbereiten

Bereitet eine neue Version des Projekts vor: Vorbedingungen prüfen, Versionsnummer festlegen, ein lesbares
Änderungsprotokoll erzeugen, Version setzen, taggen. Ist im Projekt bereits ein Release-Vorgang automatisiert
(CI-Pipeline, semantic-release o. Ä.), beschreibt dieser Skill nur noch die Vorbedingungen, die vor dem
Auslösen dieser Automatik erfüllt sein müssen — er ersetzt sie nicht.

## Ablauf

1. **Vorbedingungen prüfen.**
   - `git status`: Arbeitsbaum muss sauber sein.
   - Pflichtläufe grün: Lint, Typecheck, Tests (Befehle aus `AI-CONFIG.md` § Technik), bei UI-relevanten
     Änderungen auch E2E.
   - `docs/ai/backlog.md` auf offene kritische Punkte sichten, die vor einem Release noch entschieden werden
     müssten. Kritische offene Punkte werden {{AUFTRAGGEBER}} vorgelegt, nicht stillschweigend übergangen.
2. **Prüfen, ob ein automatisierter Release-Vorgang existiert** (z. B. `.github/workflows/`, semantic-release
   in den Skripten). Falls ja: hier abbrechen, die Automatik auslösen, nur die Vorbedingungen aus Schritt 1
   gelten als Auftrag dieses Skills.
3. **Versionsnummer festlegen.** Semantische Versionierung (`MAJOR.MINOR.PATCH`): einen Bruch mit der
   bisherigen Schnittstelle/dem bisherigen Verhalten erkennen und benennen (MAJOR), neue, abwärtskompatible
   Funktionalität (MINOR), reine Fehlerbehebung (PATCH).
4. **Änderungsprotokoll erzeugen.** Commits seit dem letzten Tag sichten (`git log <letzter-tag>..HEAD`) und
   in ein **lesbares** Protokoll übersetzen — was Nutzer davon merken, nicht die rohe Commit-Liste. Neue
   Funktionen, Fehlerbehebungen und Breaking Changes getrennt ausweisen.
5. **Version an einer Stelle setzen** (z. B. `package.json`/Äquivalent des Stacks) und das Änderungsprotokoll
   ablegen. Keine sonstige Funktionsänderung in diesem Commit.
6. **Commit und Tag.** Ein eigener Commit für die Versionsanhebung, danach den Tag setzen (`vX.Y.Z`).
7. **Verbuchen.** Ledger-Eintrag mit Version, Datum und Kurzfassung der Änderungen; danach Checkliste
   „Aufgabe abschließen" (`/commit`), sofern der Tag-Commit das nicht schon abdeckt.

## Grenzen

- Kein Release bei rotem Pflichtlauf — auch nicht „nur dieses eine Mal".
- Keine Funktionsänderung im Release-Commit; Funktionsänderungen gehören in vorangegangene, eigene Commits.
- Ist ein Release-Vorgang im Projekt automatisiert, wird er genutzt statt umgangen — dieser Skill prüft dann
  nur die Vorbedingungen und löst die Automatik aus, statt sie nachzubauen.
- Die Versionsnummer wird nicht geraten: ein Bruch, der nicht als solcher erkannt wird, gehört als Frage an
  {{AUFTRAGGEBER}}, wenn unklar ist, ob er MAJOR- oder MINOR-Charakter hat.
