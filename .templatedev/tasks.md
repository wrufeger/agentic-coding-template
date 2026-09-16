# Aufgaben für die Erweiterung des "Agentic Coding Template" Projekts

Hier trägt Wolfgang ein, was zu tun ist — formlos, ein Satz genügt. Der Orchestrator macht daraus eine
nummerierte Aufgabe (`T<n>`), arbeitet sie ab und hält den Stand nach; was unklar bleibt, wird zu einer Frage
in `questions.md`.

Marker: ✅ erledigt · 🔄 läuft oder wartet · ❓ Rückfrage offen.

---

## Aufgaben für den Assistenten

- Ist ein Zugang auf Repositories (github, gitlab, bitwarden, ...) eingerichtet (Zugangsdaten oder MCP-Server) soll der Entwickler Zugriff darauf haben,
  um z.B. Pull Requests oder Merge Requests zu erstellen. Ggf. passende Skills erstellen, die den Prozess begleiten:
    - Titel/Beschreibung für einen PR erstellen (Diff aktueller Branch und Zielbranch, bzw. default Branch des Projektes. User kann ihn definieren und er wird gespeichert, als Standard "development", "develop" oder "main" versuchen)
    - Rückfrage User ob der PR durch die KI erstellt werden darf
- Ist ein Zugang für Issuetracker eingerichtet (github/gitlab issues, Jira, Youtrack, ...), Funktionen zum Erstellen von Tickets und/oder Issues anbieten, sowie um an Issues/Stories zu arbeiten:
    - "Starte Arbeit an Issue xyz" -> Beschreibung anrufen, Branch "feature/xyz" oder "bugfix/xyz" anlegen, Zusammenfassung/Arbeitsauftrag anzeigen, mit dem User zusammen Aufgaben für KI und/oder Entwickler erstellen, Backlog aktualisieren, Doku anpassen, ...
    - "zeige issues", "zeige anstehende Aufgaben aus Jira", "zeige alle mir zugeordneten, offenen Stories", ...
- vor der Nutzung obiger Tools muß einmalig der Aufruf geprüft, sowie verfügbare Tools ausgelesen und dokumentiert werden. Ggf. Hinweise für den User anzeigen, wie er MCP korrekt einrichtet oder welche Lösungsansätze es gibt.

Daraus nummeriert (Wolfgangs Einträge oben bleiben im Wortlaut stehen). Umgesetzt wird im Template,
belegt im Testprojekt `bandliste`. Die Test-Aufgabe dafür kommt erst unter „Aufgaben nur für Wolfgang",
wenn T1–T3 committet und gepusht sind:

- [ ] **T1 · Zugänge zu Repo- und Issue-Diensten einmalig prüfen und dokumentieren** ❓
  Ziel: Ein Projekt weiß, welche Dienste (GitHub, GitLab, Jira, YouTrack, …) per MCP oder Zugangsdaten
    erreichbar sind und welche Werkzeuge sie anbieten — Voraussetzung für T2 und T3.
  Schritte:
  1. Konzept nach Checkliste „Idee oder Änderungswunsch aufnehmen": Erkennung (MCP-Server aus
     `.mcp.json`/`mcp-katalog.md`, CLI wie `gh`/`glab`, Token in `.env`), Probeaufruf nur lesend, Ablage des
     Ergebnisses, Hinweise bei fehlender oder fehlerhafter Einrichtung.
  2. Nach Entscheidung umsetzen (Script und/oder Skill), an einem Testprojekt belegen.
  Entschieden: Weg REST-Script/CLI/MCP (Q8); Ablage `docs/project/integrations.md`, Skill `/integrations` (Q9);
    GitLab und GitHub (Q11). Konzept: `konzept-repo-issues.md`.
  Stand 2026-09-16: entschieden, startklar.

- [ ] **T2 · Pull/Merge Requests vorbereiten und nach Zustimmung erstellen** ❓
  Ziel: Ein Skill schreibt Titel und Beschreibung aus dem Diff gegen den Zielbranch und legt den PR/MR erst
    nach ausdrücklicher Zustimmung an.
  Schritte:
  1. Konzept: Zielbranch-Ermittlung (gespeicherter Wert, sonst `development`/`develop`/`main`), Ablageort
     des Werts, Ablauf der Zustimmung, Abgrenzung zu `/commit` und `/release`.
  2. Nach Entscheidung Skill bauen, an einem Testprojekt mit echtem Remote belegen.
  Offen: T1.
  Entschieden: Vorschau plus „ja" je Aktion, `AGENTS.md` wird ergänzt (Q10); GitLab und GitHub (Q11).
  Stand 2026-09-16: entschieden, wartet auf T1.

- [ ] **T3 · Issues und Stories anzeigen, anlegen und bearbeiten** ❓
  Ziel: Aus Sätzen wie „zeige meine offenen Stories" oder „Starte Arbeit an Issue xyz" wird ein geführter
    Ablauf: Beschreibung holen, Branch `feature/…`/`bugfix/…`, Arbeitsauftrag, Aufgaben für KI und Entwickler,
    Backlog und Doku nachziehen.
  Schritte:
  1. Konzept: welche Tracker zuerst, Befehlssätze, Zuordnung Issue → `T<n>`/Story, Schreibzugriffe nur mit
     Freigabe (`AGENTS.md` § „Zugriff auf laufende Systeme").
  2. Nach Entscheidung in Teilaufgaben schneiden (lesen zuerst, dann anlegen, dann „Arbeit starten").
  Offen: T1.
  Entschieden: Freigabe wie T2 (Q10); GitLab und GitHub, Jira/YouTrack später (Q11).
  Stand 2026-09-16: entschieden, wartet auf T1.

- [ ] **T5 · Template-Entwicklung als normales Projekt führen** ❓
  Ziel: Die Arbeit am Template folgt denselben KI-Regeln und derselben Ordnerstruktur wie ein per
    `/create-project` angelegtes Projekt (u. a. Formregeln für Fragen und Aufgaben) und lässt sich per
    `/update-template` aktualisieren; die Sonderfälle „noch nicht initialisiert" entfallen möglichst ganz.
  Schritte:
  1. Konzept `.templatedev/concept-project-structure.md` zur Variante aus Q7: welche Sonderfälle entfallen
     (103 Stellen in `.claude/scripts/`), welche geerbten Root-Skills in `.templatedev/` überschrieben oder
     gesperrt werden müssen (z. B. `/finalize`, `/create-project`), wie der Abgleich der Struktur läuft.
  2. Nach Entscheidung in Teilaufgaben schneiden; Inhalte übernehmen (Backlog, Fragen, Journal, Regeln) und
     `questions.md`/`tasks.md` auf die Formregeln aus `docs/ai/README.md` bringen.
  3. Beleg: `/update-template` im neuen Projekt und in `bandliste`, `check-refs.py` ohne tote Verweise.
  Offen: Q12, Q13, Q14 (Konzept `concept-project-structure.md`).
  Stand 2026-09-16: aufgenommen, noch nicht begonnen.


---

## Aufgaben nur für Wolfgang

**Tabu-Bereich:** Kein Assistent führt Einträge in diesem Abschnitt aus — hier stehen Dinge, die fehlende
Rechte, ein Produktionsrisiko oder eine Entscheidung betreffen, die nur ein Mensch treffen darf (Zugangsdaten
anlegen, Produktions-Deployments, endgültiges Löschen, Rechte- und Kontenänderungen).

Jede Aufgabe hier hat zusätzlich eine `* Antwort:`-Zeile. Dort schreibt Wolfgang formlos, was gelten
soll — Stichworte reichen:

- **erledigt** — `* Antwort: erledigt, Konto heißt monitor-readonly, Passwort in .env`
  Der Orchestrator verbucht die Aufgabe und übernimmt die Zusatzangaben.
- **delegiert** — `* Antwort: mach du, Zugang liegt in .env`
  Die Aufgabe wandert in den oberen Abschnitt. Die erweiterten Rechte gelten nur für genau diese Aufgabe und
  werden mit Datum im `ledger.md` festgehalten.
- **Rückfrage oder Bedingung** — `* Antwort: erst nach dem Release` oder `* Antwort: warum braucht ihr das?`
  Der Orchestrator antwortet darunter, die Aufgabe bleibt offen.

Wolfgangs Zeilen bleiben unverändert stehen; der Orchestrator kommentiert nur darunter.
