> Datenstand: 2026-09-17 – Status: aktuell

# Dokumentations-Index — Template-Entwicklung

Zweck: eine Sitzung (Mensch oder Assistent) soll in wenigen Minuten ein vollständiges, belastbares Bild
dieses Pflegeprojekts bekommen. Tabelle statt Fließtext.

Dieses Projekt ist **die Weiterentwicklung des Agentic-Coding-Templates selbst** (T5) — seit T5 als eigenes
Projekt in derselben Struktur, die `/act-create-project` für abgeleitete Projekte anlegt. Es gehört nicht
zum Lieferumfang eines Projekts, das aus dem Template entsteht (`template_only` in
`../.claude/template.json`).

## Reihenfolge zum Einlesen

1. `docs/ai/ledger.md` — was zuletzt geschah.
2. `docs/ai/board.md` — aktueller Stand, nächster Schritt.
3. `docs/ai/tasks.md` — was beauftragt ist.
4. `docs/ai/backlog.md` — was offen ist.
5. Diese Tabelle — je nach Aufgabe gezielt die passende Datei.

## Index

| Datei | Inhalt (Kurzfassung) | Datenstand | Wann lesen |
| :--- | :--- | :--- | :--- |
| `docs/ai/board.md` | Einstiegs-/Wiedereinstiegsboard | 2026-09-17 | immer zuerst |
| `docs/ai/tasks.md` | Aufgaben (`T<n>`) inkl. Tabu-Abschnitt „nur für Wolfgang" | 2026-09-17 | vor jeder neuen Aufgabe |
| `docs/ai/tasks_archive.md` | Erledigte Aufgaben im Volltext | 2026-09-17 | bei Bedarf nachschlagen |
| `docs/ai/questions.md` | Offene Fragen (`Q<n>`) | 2026-09-17 | nach jeder Antwort |
| `docs/ai/questions_archive.md` | Beantwortete/archivierte Fragen | 2026-09-17 | bei Bedarf nachschlagen |
| `docs/ai/ledger.md` | Sitzungsjournal mit Belegen | 2026-09-17 | zur Historie/Übergabe |
| `docs/ai/backlog.md` | Priorisierte Verbesserungsvorschläge (`B<n>`) | 2026-09-17 | vor größeren Umbauten |
| `docs/project/coding_rules.md` | Regeln für die Arbeit am Template selbst | 2026-09-17 | vor jeder Änderung an der Mechanik |
| `docs/project/test-projects.md` | Testprojekte und ihr letzter geprüfter Stand | 2026-09-17 | vor/nach einem Testlauf |
| `docs/project/concepts/project-structure.md` | Konzept T5: diese Projektstruktur selbst | 2026-09-17 | beim Weiterbau von T5 |
| `docs/project/concepts/feedback.md` | Konzept: Rückmeldung abgeleiteter Projekte | 2026-09-17 | vor Änderungen am Feedback-Weg |
| `docs/project/concepts/repo-issues.md` | Konzept T1–T3: Repo-/Issue-Dienste | 2026-09-17 | vor Änderungen an T1–T3 |
| `docs/project/data/README.md` | Messwerte, Testprotokolle, Auswertungen | 2026-09-17 | bei Bedarf nachschlagen |
| `scripts/README.md` | Scripte der Template-Entwicklung (Feedback-Endpunkt/-Abholung, Testprojekte) | 2026-09-17 | vor Änderungen an den Scripten |

Noch nicht vorhanden, folgt mit T5 Schritt 3 (`scripts/sync-rules.py`, gerenderte Kopie aus dem Root):
`AGENTS.md`, `CLAUDE.md`, `docs/ai/README.md` (Formregeln), `docs/ai/checklists.md`.

## Konventionen für diese Doku

Dieselben Regeln wie im Root-Template, `../../docs/README.md` § „Konventionen für diese Doku": Datenstand-
Kopfzeile `> Datenstand: JJJJ-MM-TT – Status: <wort>` (Status `aktuell`/`Entwurf`/`veraltet`, Datum = letzte
Prüfung gegen die Wirklichkeit, nicht die letzte Textänderung), Annahmen mit **(Annahme)** markiert, Secrets
niemals im Klartext (Ablage: `.env`, gitignored, sobald echte Werte eingetragen sind).
