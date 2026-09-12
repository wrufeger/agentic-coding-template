> Datenstand: {{DATUM}} – Status: Vorlage, noch nicht projektspezifisch

# Aufgaben — {{PROJEKTNAME}}

Hier schreibt {{AUFTRAGGEBER}} anstehende Aufgaben, Bugs und Ideen stichpunktartig auf. Der Orchestrator
arbeitet diese direkt ab und dokumentiert alles ODER schreibt Fragen/Unklarheiten nach `questions.md` oder stellt
kurze, einfache Rückfragen direkt im Gespräch.

Status-Marker (vom Orchestrator gesetzt): ✅ erledigt · 🔄 teilweise/wartet · ❓ Rückfrage in `questions.md`.

Jede Aufgabe bekommt eine fortlaufende Nummer mit Präfix `A<n>` (z. B. `A7`) — projektweite Referenz-ID, die in
Ledger und Commits zitiert wird und **nie neu vergeben** wird, auch nach dem Archivieren nicht. Fragen in
`questions.md` laufen analog unter `F<n>`. Format je Aufgabe:

```
- [ ] **A7 · Kurztitel der Aufgabe** 🔄
  Ziel: ein Satz, woran man erkennt, dass die Aufgabe erledigt ist.
  Schritte:
  1. …
  2. …
  Stand 2026-01-31: was zuletzt passiert ist, was gerade blockiert.
```

Die `Stand <Datum>:`-Zeile wird bei jeder Berührung der Aufgabe **aktualisiert**, nicht überschrieben oder
gelöscht (ältere Stände ggf. darüber stehen lassen, wenn sie noch relevant sind). Erledigte Aufgaben (✅) werden
**mit Volltext** nach `docs/ai/tasks_archive.md` verschoben (nicht gelöscht) — der Beleg für die Erledigung
bleibt im `ledger.md`.

**Kurz und übersichtlich, kein Fließtext.** Diese Datei wird im Alltag überflogen, nicht gelesen:

- Titel eine Zeile, `Ziel:` ein Satz, Schritte als nummerierte Stichpunkte — je Schritt eine Zeile, Imperativ,
  keine Erklärungen.
- Keine Absätze, keine Prosa, keine Tabellen. Was länger wird, gehört in `docs/project/` und wird von hier aus
  nur verlinkt.
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

In die `* Antwort:`-Zeile schreibt {{AUFTRAGGEBER}} formlos, was gelten soll — Stichworte reichen:

- **erledigt** („erledigt, Konto heißt `ro-monitor`") — der Orchestrator verbucht es und ergänzt die
  Zusatzinfos zur Umsetzung in der Aufgabe.
- **delegiert** („mach du, Zugang liegt in `.env`") — die Aufgabe wandert damit aus dem Tabu-Bereich in den
  oberen Abschnitt; erweiterte Rechte gelten nur für genau diese Aufgabe und werden im Ledger mit Datum
  festgehalten (`AGENTS.md` § „Zugriff auf laufende Systeme").
- **Rückfrage oder Bedingung** („erst nach dem Release", „warum braucht ihr das?") — der Orchestrator antwortet
  darunter, die Aufgabe bleibt offen.

{{AUFTRAGGEBER}}s Zeilen bleiben unverändert stehen; der Orchestrator kommentiert nur darunter.

*(noch keine)*
