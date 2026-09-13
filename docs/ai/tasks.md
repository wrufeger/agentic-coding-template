> Datenstand: {{DATUM}} – Status: Vorlage, noch nicht projektspezifisch

# Aufgaben — {{PROJEKTNAME}}

Hier schreibt {{AUFTRAGGEBER}} anstehende Aufgaben, Bugs und Ideen stichpunktartig auf. Der Orchestrator
arbeitet diese direkt ab und dokumentiert alles ODER schreibt Fragen/Unklarheiten nach `questions.md` oder stellt
kurze, einfache Rückfragen direkt im Gespräch.

Status-Marker (vom Orchestrator gesetzt): ✅ erledigt · 🔄 teilweise/wartet · ❓ Rückfrage in `questions.md`.

Jede Aufgabe bekommt eine fortlaufende Nummer mit Präfix `A<n>` (z. B. `A7`) — projektweite Referenz-ID, die in
Ledger und Commits zitiert wird und **nie neu vergeben** wird, auch nach dem Archivieren nicht. Fragen in
`questions.md` laufen analog unter `F<n>`. Format je Aufgabe:

**Offene Aufgabe:**

```
- [ ] **A7 · Kurztitel der Aufgabe** 🔄
  Ziel: ein Satz, woran man erkennt, dass die Aufgabe erledigt ist.
  Schritte:
  1. …
  2. …
  Offen: was noch fehlt, um anfangen oder fertig werden zu können — fehlende Vorgaben, Zugänge,
    unbeantwortete Fragen (`F<n>`), abhängige Aufgaben (`A<n>`). Entfällt, wenn nichts offen ist.
  Entschieden: was bereits feststeht und nicht neu verhandelt wird, je Punkt eine Zeile mit Verweis
    (`ADR-<n>`, `F<n>`). Entfällt, wenn nichts entschieden wurde.
  Stand 2026-01-31: eine Zeile — wo die Aufgabe gerade steht.
```

**Erledigte Aufgabe** — Haken gesetzt, Marker ✅, und statt Schritten das Ergebnis:

```
- [x] **A7 · Kurztitel der Aufgabe** ✅
  Ziel: unverändert stehen lassen.
  Ergebnis: was tatsächlich getan wurde, in ein bis drei Zeilen, mit Beleg (Commit-Hash, Datei, Testlauf).
  Stand 2026-02-03: erledigt.
```

**Der Entscheidungsverlauf gehört nicht hierher.** Wie eine Entscheidung zustande kam, steht in
`docs/project/decisions.md` (ADR) und in `docs/ai/questions_archive.md`; was währenddessen passiert ist, im
`ledger.md`. In der Aufgabe steht nur das **Ergebnis** dieses Verlaufs — sonst wächst jede Aufgabe zu einem
Protokoll, das niemand mehr überfliegt.

Die `Stand <Datum>:`-Zeile wird bei jeder Berührung **aktualisiert** und bleibt **eine** Zeile; ältere Stände
werden ersetzt, nicht gestapelt. Erledigte Aufgaben (✅) werden **mit Volltext** nach
`docs/ai/tasks_archive.md` verschoben (nicht gelöscht) — spätestens beim nächsten Lauf der Checkliste
„Aufgabe abschließen", damit diese Datei nur zeigt, was noch aussteht. Der Beleg für die Erledigung bleibt im
`ledger.md`.

**Kurz und übersichtlich, kein Fließtext.** Diese Datei wird im Alltag überflogen, nicht gelesen:

- Titel eine Zeile, `Ziel:` ein Satz, Schritte als nummerierte Stichpunkte — je Schritt eine Zeile, Imperativ,
  keine Erklärungen.
- Keine Absätze, keine Prosa, keine Tabellen. Was länger wird, gehört in `docs/project/` und wird von hier aus
  nur verlinkt.
- `Offen:` und `Entschieden:` sind Stichpunktlisten, keine Begründungen — die Begründung steht im ADR.
- Eine Aufgabe = ein Ergebnis. Braucht sie mehr als etwa fünf Schritte oder mehrere Entscheidungen, wird sie
  in mehrere Aufgaben mit eigenen Nummern geteilt.
- Unklarheiten werden nicht in der Aufgabe ausdiskutiert — sie werden zu einer Frage in `questions.md`.

---

## Aufgaben für den Assistenten

*(noch keine — nach dem Start des Projekts hier eintragen)*

---

## Aufgaben nur für {{AUFTRAGGEBER}}

**Tabu-Bereich — siehe `AGENTS.md`:** Kein Assistent (Orchestrator oder Worker) führt Einträge in diesem
Abschnitt aus. Der Orchestrator darf Einträge hier nur ergänzen, präzisieren oder als erledigt markieren, wenn
{{AUFTRAGGEBER}} es meldet. Dasselbe Aufgabenschema (Nummer `A<n>`, Ziel, Schritte, `Stand <Datum>:`) gilt auch
hier, **plus eine eigene `* Antwort:`-Zeile** je Aufgabe:

```
- [ ] **A12 · Zugang zum Monitoring anlegen** ❓
  Ziel: Assistent kann die Dashboards lesen.
  Schritte:
  1. Nur-Lese-Konto anlegen.
  2. Zugangsdaten in `.env` eintragen (nicht ins Repo).
  Stand 2026-01-31: wartet auf {{AUFTRAGGEBER}}.
  * Antwort:
```

In die `* Antwort:`-Zeile schreibt {{AUFTRAGGEBER}} formlos, was gelten soll — Stichworte reichen. Drei Fälle,
jeweils mit einer möglichen Antwortzeile als Beispiel:

- **erledigt** — `* Antwort: erledigt, Konto heißt monitor-readonly, Passwort in .env`
  Der Orchestrator verbucht die Aufgabe und übernimmt die Zusatzangaben. Solche Angaben gehören dazu:
  Kontoname und Ablageort sind Entscheidungen von {{AUFTRAGGEBER}}, der Assistent kennt sie sonst nicht.
- **delegiert** — `* Antwort: mach du, Zugang liegt in .env`
  Die Aufgabe wandert aus dem Tabu-Bereich in den oberen Abschnitt. Erweiterte Rechte gelten nur für genau
  diese Aufgabe und werden im Ledger mit Datum festgehalten (`AGENTS.md` § „Zugriff auf laufende Systeme“).
- **Rückfrage oder Bedingung** — `* Antwort: erst nach dem Release` oder `* Antwort: warum braucht ihr das?`
  Der Orchestrator antwortet darunter, die Aufgabe bleibt offen.

{{AUFTRAGGEBER}}s Zeilen bleiben unverändert stehen; der Orchestrator kommentiert nur darunter.

*(noch keine)*
