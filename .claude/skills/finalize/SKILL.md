---
name: finalize
description: Einrichtung abschließen - Projekterstellung oder Nachrüsten für beendet erklären und die Einrichtungswerkzeuge aus dem Projekt entfernen. Auslöser - "/finalize", "Projekterstellung abschließen", "Nachrüsten abschließen", "Einrichtung fertig".
---

# Einrichtung abschließen (nur Hauptkontext)

Erklärt die Einrichtung dieses Projekts für beendet und entfernt danach alles, was nur zum Anlegen bzw.
Nachrüsten gebraucht wurde. Mechanik: `.claude/scripts/finish-setup.py`. Läuft **nie** in einem Sub-Agenten —
es wird gelöscht, und nur der Orchestrator committet.

**Wann.** Nicht am Ende von `/create-project` oder `/apply-template` — die Einrichtung ist dort meist noch
nicht wirklich fertig: `docs/project/` will nachgeschärft, `AI-CONFIG.md` nachjustiert, vielleicht muss ein
zweites Mal nachgerüstet werden. Der Abschluss ist deshalb ein eigener Schritt, den {{AUFTRAGGEBER}} auslöst,
wenn er mit allem durch ist. Bis dahin erinnert der SessionStart-Hook bei jedem Sitzungsstart kurz daran.

**Was danach nicht mehr geht.** `create-project`, `apply-template` und die Struktur-Migration sind im Projekt
anschließend nicht mehr aufrufbar. Das ist beabsichtigt: Ein eingerichtetes Projekt soll sich nicht versehentlich
noch einmal einrichten lassen. Weiter funktionieren `/update-template`, `sync-config.py` (`AI-CONFIG.md` wirkt
unverändert laufend), `guidelines.py`, `ai-log.py` und die Alltags-Skills `/commit` und `/audit-docs`.

## Ablauf

1. **Vorbedingungen prüfen.** `git status` — der Arbeitsbaum muss sauber sein. Ist er es nicht, zuerst die
   laufende Aufgabe abschließen (`/commit`); das Aufräumen löscht Dateien und soll für sich im Verlauf stehen.
2. `python .claude/scripts/finish-setup.py --plan` ausführen und die Ausgabe **vollständig** zeigen: was
   entfernt wird, was bewusst liegen bleibt, was inhaltlich noch offen ist.
3. **Einmal nachfragen**, auch wenn {{AUFTRAGGEBER}} den Skill selbst aufgerufen hat — der Schritt ist nicht
   ohne Weiteres rückgängig zu machen (nur über `git revert` bzw. `git checkout` des Commits):

   „Einrichtung abschließen? Danach sind `create-project` und `apply-template` in diesem Projekt nicht mehr
   verfügbar. a) ja b) noch nicht"

   Ohne Antwort **nicht** ausführen (`AGENTS.md` — keine Standardantwort annehmen).
4. Meldet der Plan unter „Noch einzuarbeiten" fremde KI-Regeldateien (`.junie/guidelines.md`, `.clinerules`,
   `.windsurfrules`, `.cursorrules`, `.github/instructions/`, `AGENT.md`), diese **vor** dem Abschluss
   erledigen — sonst gelten zwei Regelwerke nebeneinander und laufen auseinander:
   - Inhalt nach `docs/project/coding_rules.md` übernehmen, soweit er dort noch nicht steht (Sub-Agent
     `doc-writer`, Sonnet). Bei Widersprüchen gilt die strengere Regel.
   - Die Altdatei danach auf einen Verweis eindampfen, Beispiel für `.junie/guidelines.md`:

     ```markdown
     # Projektregeln

     Die verbindlichen Regeln dieses Projekts stehen in `AGENTS.md` im Repo-Root (werkzeugunabhängig) und
     in `docs/project/coding_rules.md` (Stil- und Sprachregeln). Diese Datei wird nicht mehr gepflegt.
     ```
   - Nur löschen statt eindampfen, wenn das Werkzeug die Datei gar nicht mehr braucht und {{AUFTRAGGEBER}}
     zustimmt.
5. `python .claude/scripts/finish-setup.py --apply` ausführen, Ausgabe zeigen.
6. Ergebnis verbuchen: Ledger-Eintrag „Einrichtung abgeschlossen" mit der Liste der entfernten Dateien,
   Board-Kurzbilanz nachziehen.
7. Commit per Pathspec (die Löschungen sind bereits vorgemerkt, wenn das Script `git rm` genutzt hat —
   `git status` prüfen und nur die betroffenen Pfade committen).

## Grenzen

- Kein Projektinhalt wird angefasst: nichts unter `docs/project/` (außer der Regelübernahme in Schritt 4),
  kein Anwendungscode, keine Abhängigkeit.
- `docs/ai/checklists.md` verliert die beiden Abschnitte „Neues Projekt" und „Projekt nachrüsten", weil sie
  im eingerichteten Projekt nur noch in die Irre führen. Alle übrigen Checklisten bleiben.
- Das Script entfernt sich am Ende selbst. Ein zweiter Lauf ist damit weder möglich noch nötig.
- Im Template-Checkout selbst (Marker `is_template` in `.claude/template.json`) verweigert das Script den
  Dienst — dort werden die Einrichtungswerkzeuge gepflegt, nicht gelöscht.
