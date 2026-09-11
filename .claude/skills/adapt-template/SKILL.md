---
name: adapt-template
description: Checkliste Template anpassen - Platzhalter ersetzen, Stack-Regeln ergänzen, unnötige Dateien entfernen.
---

# Template anpassen

Setzt die werkzeugneutrale Checkliste „Template anpassen" aus `docs/ai/checklists.md` um. Läuft im
Hauptkontext, da es Entscheidungen mit {{AUFTRAGGEBER}} braucht (Stack, welche Dateien entfernt werden).

## Ablauf
1. `grep -rn "{{" .` im ganzen Repo — jeden Treffer durchgehen, Platzhalter durch echte Werte ersetzen.
2. `docs/project/coding_rules.md` § „Stack-spezifisch" mit {{AUFTRAGGEBER}} zusammen ausfüllen.
3. `.github/workflows/ci.yml` (und `.aider.conf.yml`, falls Aider genutzt wird) auf echte Befehle umstellen.
4. Nicht benötigte Vorlagendateien (z. B. Agenten für einen nicht genutzten Stack) entfernen, `docs/README.md`
   nachziehen.
5. Datenstand-Kopfzeilen aller Doku-Dateien von „Status: Vorlage" auf ein echtes Datum umstellen.
6. `docs/ai/board.md` mit dem realen Start-Stand befüllen, ersten `docs/ai/ledger.md`-Eintrag schreiben.
7. Zum Schluss: `git status` prüfen, Commit per Pathspec (Skill `/session-wrapup`).
