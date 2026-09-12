---
name: audit-docs
description: Doku gegen den echten Stand prüfen und nachziehen - docs/project gegen den Code, docs/ai auf Ordnung.
context: fork
agent: general-purpose
model: claude-sonnet-5
argument-hint: "[project|ai|alle]"
---

# Doku prüfen und nachziehen

Läuft als Fork in einem `general-purpose`-Worker, der Fan-out und Auswertung übernimmt; der Hauptkontext
prüft danach die Diffs und committet (Skill `/commit`, nicht delegierbar). Bewusst **kein** projekteigener
Agent als Träger: Der Doku-Abgleich gehört nicht zur optionalen Wartung und muss auch dann laufen, wenn diese
abgewählt ist (`AI-CONFIG.md` § Betrieb).

Ersetzt die früheren Skills `/project-docs` und `/docs-audit`: Nachziehen und Prüfen sind derselbe Vorgang —
wer nachzieht, gleicht zuerst ab.

## Argumente

- **ohne Argument / `alle`** — beide Bereiche nacheinander.
- **`project`** — nur `docs/project/` gegen den echten Code.
- **`ai`** — nur `docs/ai/` auf Ordnung (schnell, kein Code-Zugriff nötig).

Typischer Fall nach einer Feature-Welle: `alle`. Wer nur wissen will, ob die Architekturdoku noch stimmt:
`project`. Vor einer Übergabe oder nach längerer Pause: `ai`.

## Bereich `project` — Doku gegen Code

1. `git status` und `git diff --stat docs`: offene Änderungen früherer Sitzungen sichten.
2. Fan-out, beide gleichzeitig starten: `explorer` (Sonnet) ermittelt die Code-Realität — welche Module,
   Endpunkte, Tabellen, Befehle und Tests wirklich existieren, mit `Datei:Zeile`-Belegen; `doc-writer`
   (Sonnet) gleicht `docs/project/*` dagegen ab und korrigiert direkt. Bei größeren Projekten je Doku-Bereich
   ein eigenes Paar.
3. Nachziehen, was die Welle gebracht hat, nach den Regeln der Checkliste „Doku prüfen und nachziehen"
   (`docs/ai/checklists.md`): neue Schnittstelle oder Tabelle nach `architecture.md`/`features.md`, neu
   gelernte Konvention als Regel nach `coding_rules.md`, geänderte Tests nach `testing.md`, schwere Fehler
   nach `docs/project/incidents/`.
4. `doc-writer` aktualisiert `docs/README.md` (Index, Datenstände).

## Bereich `ai` — Arbeitsordner auf Ordnung

Ohne Code-Zugriff, reine Formprüfung von `docs/ai/`:

- **Aufgaben:** als ✅ markierte Aufgaben, die noch nicht in `tasks_archive.md` stehen. Aufgaben ohne
  `Stand <Datum>:` oder mit einem Stand, der älter ist als der letzte Journaleintrag dazu. Doppelt vergebene
  oder übersprungene Nummern.
- **Fragen:** beantwortete Fragen ohne Bestätigungszeile darunter, verbuchte Fragen, die noch nicht im Archiv
  sind, Teilfragen-Blöcke (`F5a`/`F5b`) mit nur teilweisen Antworten, Fragen ohne vorgegebene
  Antwortmöglichkeiten.
- **Board:** Kurzbilanz, nächster Schritt und offene Freigaben gegen den tatsächlichen Stand aus Journal und
  Aufgaben.
- **Journal:** Einträge ohne Beleg, fehlende Verdichtung nach den Regeln im Dateikopf.
- **Umbauliste:** Punkte, die längst umgesetzt oder abgelehnt wurden und nur noch Platz kosten.

Gefundene Abweichungen werden **korrigiert, nicht nur gemeldet**, solange es reine Formarbeit ist
(archivieren, Stand nachtragen, Board aktualisieren). Alles, was eine Entscheidung von {{AUFTRAGGEBER}}
braucht, wird als Frage in `questions.md` gestellt.

## Rückgabe an den Hauptkontext

Kurzfazit, Abweichungstabelle (≤ 15 Zeilen), geänderte Dateien nur als `Pfad · Abschnitt · 1 Zeile`,
Vorschläge für `docs/ai/tasks.md`/`questions.md`.

## Abschluss (Hauptkontext, nicht delegierbar)

`git status`/`git diff --stat docs` gegenprüfen, Vorschläge einarbeiten, dann Skill `/commit`.

## Grenzen

Nichts wird am Code geändert; Findings, die Code-Änderungen brauchen, werden Aufgaben in `docs/ai/tasks.md`.
Kein Doku-Eintrag ohne Prüfung am Code — die Doku beschreibt den IST-Zustand, nicht den Wunsch. Was noch nicht
gebaut ist, gehört auf die Umbauliste.

## Fallback bei fehlendem Agent-Typ

Ist ein benötigter Agent-Typ (`explorer`, `doc-writer`) in der laufenden Installation nicht registriert,
stattdessen `general-purpose` starten und im Auftrag die passende Agenten-Datei (`.claude/agents/<name>.md`)
als verbindliche Rolle referenzieren („Arbeite nach der Rolle in dieser Datei"). Gilt sinngemäß für jeden
Skill mit Fan-out auf Sub-Agenten.
