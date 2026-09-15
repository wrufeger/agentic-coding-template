# Template-Entwicklung

Arbeitsordner für die Weiterentwicklung **dieses Template-Repos** — hier stehen Backlog, Fragen, Journal,
Regeln und die Übersicht der Testprojekte. Er gehört nicht zum Lieferumfang: Beim Anlegen eines Projekts wird
er entfernt, beim Nachrüsten nie kopiert, und ein Template-Update trägt ihn nicht in abgeleitete Projekte
(`template_only` in `.claude/template.json`).

Warum nicht `docs/ai/`? Weil dort nur **Vorlagen** liegen: Board, Aufgaben, Fragen, Ledger und Backlog
sind im Template leere Gerüste, die jedes abgeleitete Projekt mit eigenen Inhalten füllt. Stünde die
Template-Entwicklung dort, wanderte sie in jedes Projekt mit. Dasselbe gilt für `docs/project/`.

**Alles hier ist versioniert.** Das war zwischenzeitlich anders (gitignored, dann in ein eigenes Projekt
ausgelagert) — beides hat sich nicht bewährt, siehe `ledger.md` zum 2026-09-14. Kurz: Ohne Versionierung gibt
es keine Historie und keine Sicherung; in einem getrennten Repo liegen Struktur und Notizen in verschiedenen
Fenstern, obwohl man beim Arbeiten beides zugleich braucht.

| Datei | Inhalt |
| :--- | :--- |
| `INDEX.md` | diese Übersicht |
| `README.md` | Testprojekte: welche es gibt, welchen Weg sie abdecken, ihr letzter geprüfter Stand |
| `backlog.md` | Backlog: priorisierte Verbesserungsvorschläge, Nummern bleiben stabil |
| `questions.md` | offene Entscheidungen zur Weiterentwicklung (`Q<n>`) |
| `ledger.md` | Journal: was in welcher Sitzung passiert ist, mit Belegen |
| `regeln.md` | Regeln für die Arbeit **am Template selbst** |
| `scripts/` | Werkzeuge nur für die Template-Entwicklung — u. a. die beiden Seiten der freiwilligen Rückmeldung (Endpunkt und Abholung), siehe `scripts/README.md` |
| `testprojekte.py` | gleicht die Tabelle in `README.md` mit dem echten Stand der Testprojekte ab |
| `daten/` | Messwerte, Testprotokolle, Auswertungen — zu lang für den Fließtext |

## Wie hier gearbeitet wird

- **Sitzungsbeginn:** `ledger.md` (letzter Stand) und `backlog.md` (was offen ist). Dazu
  `python .templatedev/testprojekte.py --check` — er sagt, ob sich in den Testprojekten etwas getan hat und
  wann dort zuletzt `questions.md`, `questions_archive.md` und `ledger.md` geändert wurden.
- Ein Fehler, der beim Einsatz in einem Testprojekt auffällt, wird **dort** behoben (damit es weitergeht)
  **und** hier als Punkt notiert, wenn die Ursache im Template liegt. Nur im Projekt reparieren heißt: Das
  nächste Projekt tritt in dieselbe Grube.
- Eine Template-Änderung ist erst dann wirklich belegt, wenn sie an einem Testprojekt gelaufen ist. „Im
  Wegwerf-Repo getestet" ist ein Zwischenschritt, kein Ersatz.
- Nummern in `backlog.md` und `questions.md` werden nie neu vergeben, auch nicht nach dem Erledigen.
- Was dauerhaft gelten soll, gehört in `AGENTS.md`, `CLAUDE.md` oder einen Baustein unter
  `docs/project/coding_rules.d/` — nicht ins Journal. Das Journal sagt, warum etwas so ist; die Regel sagt,
  was gilt.
