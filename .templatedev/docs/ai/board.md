> Datenstand: 2026-09-17 – Status: aktuell

# Board — Was als Nächstes

Erster Blick jeder Sitzung: wo das Projekt steht, was als Nächstes drankommt, worauf gewartet wird. Eine
Bildschirmseite, nicht mehr — die Datei wird bei jeder Berührung überschrieben, nicht ergänzt. Die Historie
führt das `ledger.md`.

*Was in welchen Abschnitt gehört: `../../../docs/ai/README.md` § „Board" (eigene Fassung folgt mit T5
Schritt 3).*

Stand 2026-09-17.

## Kurzbilanz

- **T5** (diese Projektstruktur) läuft: Schritt 1 (Marker/Frontmatter) und Schritt 2 (Umzug an die
  Standardorte, `git mv`, Formregeln für Fragen/Aufgaben, Verweise nachgezogen) sind fertig. Offen sind
  Schritt 3 (Vererbung von `AGENTS.md`/`CLAUDE.md`/`docs/ai/README.md`/`docs/ai/checklists.md` per
  `scripts/sync-rules.py`), Schritt 4 (Root aufräumen) und Schritt 5 (Beleg, u. a. Sitzungswechsel nach
  `.templatedev/`).
- **T1–T3** (Zugänge zu Repo-/Issue-Diensten, PR/MR, Issues) sind entschieden und startklar, aber noch nicht
  begonnen — sie laufen nach T5.
- **Feedback-Endpunkt** (B29/B32) ist clientseitig und serverseitig gebaut (`scripts/feedback-endpoint.php`,
  `scripts/feedback-fetch.py`); offen bleibt der Rollout auf `rufeger.de`.
- Backlog hat mehrere offene Punkte ohne Zeitdruck (u. a. B25 MCP-Auswahl automatisieren, B27
  Mehrsprachigkeit-Konzept, B28 Widerspruch bei `no_replace`, B33 Tabu-Aufgaben erst bei Startklarheit
  eintragen, B34 Issue-Tracker ohne Git, B46/B47 Hook-Feinschliff, B49/B50 neue Skills).

## Als Nächstes

1. T5 Schritt 3: `scripts/sync-rules.py` bauen — erzeugt `AGENTS.md`, `CLAUDE.md`, `docs/ai/README.md`,
   `docs/ai/checklists.md` gerendert aus dem Root, `--check` als SessionStart-Hook.
2. T5 Schritt 4: Root aufräumen (Template-Blöcke in `AGENTS.md`/`CLAUDE.md` auf drei Zeilen kürzen,
   `.templatedev`-Sonderpfade aus `check-refs.py` entfernen).
3. T5 Schritt 5: Beleg — Sitzungswechsel nach `.templatedev/` (wird rechtzeitig angesagt), `/act-commit`,
   `/act-update-template` in einem Wegwerf-Klon und in `bandliste` gegenprüfen.
4. Danach T1: Zugänge zu Repo-/Issue-Diensten einmalig prüfen und dokumentieren.

## Ausstehende Freigaben

*(keine — alle offenen Fragen `Q19`–`Q23` in `questions.md` sind beantwortet und verbucht)*
