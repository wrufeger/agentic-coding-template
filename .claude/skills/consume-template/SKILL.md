---
name: consume-template
description: Checkliste Projekt nachrüsten - bestehendes Repo mit der Agentic-Coding-Grundausstattung ausstatten, IST-Zustand dokumentieren.
---

# Projekt nachrüsten

Setzt die werkzeugneutrale Checkliste „Projekt nachrüsten" aus `docs/ai/checklists.md` um (Weg 2). Läuft im
Hauptkontext, **im Ziel-Repo** — nachdem `consume-template.py` (aus dem Template-Checkout heraus) bereits
dorthin kopiert hat. Mechanik: `.claude/scripts/consume-template.py` (Kopiervorgang, läuft vorher aus dem
Template), `.claude/scripts/new-project.py` (Platzhalter/Werte), `.claude/scripts/template-update.py --graft`
(Historie verknüpfen).

## Ablauf

1. `git status` sichten, die von `consume-template.py` kopierten Dateien stichprobenartig prüfen. Die
   Ausgabe von `consume-template.py` nennt übersprungene Dateien („von Hand zusammenführen") — typischerweise
   `README.md` (wurde gar nicht kopiert) und ggf. `.gitignore`-Vorschläge.
2. Sub-Agent `explorer` (Sonnet) analysiert das bestehende Repo: Projektname (`package.json` o. Ä.), Stack,
   Verzeichnisstruktur, Tests, Befehle (Install/Dev-Start/Lint/Typecheck/Test/E2E), CI — Rückgabe ≤ 40
   Zeilen mit Belegen (`Datei:Zeile`).
3. `CONFIG.md` daraus befüllen (Projektname, Stack, Befehle; `KI-Werkzeuge` nach kurzer Rückfrage an
   {{AUFTRAGGEBER}}, welche Werkzeuge im Projekt genutzt werden). Danach `python .claude/scripts/
   new-project.py --apply` ausführen — ersetzt Platzhalter, entfernt nicht genutzte Werkzeug-Dateien, setzt
   die Werte in `.claude/template.json`.
4. `docs/project/*` mit dem **echten IST-Zustand** befüllen — nicht raten, am Code prüfen (Sub-Agent
   `doc-writer`, Sonnet). `.gitignore`-Vorschläge aus Schritt 1 übernehmen (von Hand zusammenführen, nie
   automatisch überschreiben). Im Projekt-`README.md` einen Abschnitt „Zusammenarbeit mit KI-Assistenten"
   ergänzen (Verweis auf `AGENTS.md` und `docs/ai/board.md`).
5. Ersten `docs/ai/board.md`-Stand und `docs/ai/ledger.md`-Eintrag „Template nachgerüstet" schreiben (mit
   Beleg: was `consume-template.py` kopiert/übersprungen hat, was befüllt wurde).
6. `python .claude/scripts/new-project.py --finish` ausführen (löscht `CONFIG.md`, prüft vorher Schritt 4/5).
7. Commit per Pathspec nach Freigabe von {{AUFTRAGGEBER}}.
8. `python .claude/scripts/template-update.py --graft` ausführen (nach Freigabe — erzeugt einen
   Merge-Commit ohne Änderung des Arbeitsbaums, Voraussetzung für spätere `/template-update`-Läufe).

## Grenzen

Kein Code wird am bestehenden Projekt geändert — nur die Agentic-Coding-Grundausstattung kommt hinzu. Findings
zum Code selbst (fehlende Tests, TODOs) werden Aufgaben in `docs/ai/tasks.md`, nicht direkt umgesetzt.
