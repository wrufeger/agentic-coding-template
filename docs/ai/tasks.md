> Datenstand: {{DATUM}} – Status: Vorlage, noch nicht projektspezifisch

# Aufgaben — {{PROJEKTNAME}}

Hier trägt {{AUFTRAGGEBER}} ein, was zu tun ist — formlos, ein Satz genügt. Der Orchestrator macht daraus eine
nummerierte Aufgabe (`T<n>`), arbeitet sie ab und hält den Stand nach; was unklar bleibt, wird zu einer Frage
in `questions.md`.

Marker: ✅ erledigt · 🔄 läuft oder wartet · ❓ Rückfrage offen.

*Format, Archivierung und Kurzhalte-Regeln: `README.md` § „Aufgaben".*

---

## Aufgaben für den Assistenten

*(noch keine — nach dem Start des Projekts hier eintragen)*

---

## Aufgaben nur für {{AUFTRAGGEBER}}

**Tabu-Bereich:** Kein Assistent führt Einträge in diesem Abschnitt aus — hier stehen Dinge, die fehlende
Rechte, ein Produktionsrisiko oder eine Entscheidung betreffen, die nur ein Mensch treffen darf (Zugangsdaten
anlegen, Produktions-Deployments, endgültiges Löschen, Rechte- und Kontenänderungen).

Jede Aufgabe hier hat zusätzlich eine `* Antwort:`-Zeile. Dort schreibt {{AUFTRAGGEBER}} formlos, was gelten
soll — Stichworte reichen:

- **erledigt** — `* Antwort: erledigt, Konto heißt monitor-readonly, Passwort in .env`
  Der Orchestrator verbucht die Aufgabe und übernimmt die Zusatzangaben.
- **delegiert** — `* Antwort: mach du, Zugang liegt in .env`
  Die Aufgabe wandert in den oberen Abschnitt. Die erweiterten Rechte gelten nur für genau diese Aufgabe und
  werden mit Datum im `ledger.md` festgehalten.
- **Rückfrage oder Bedingung** — `* Antwort: erst nach dem Release` oder `* Antwort: warum braucht ihr das?`
  Der Orchestrator antwortet darunter, die Aufgabe bleibt offen.

{{AUFTRAGGEBER}}s Zeilen bleiben unverändert stehen; der Orchestrator kommentiert nur darunter.

*(noch keine)*
