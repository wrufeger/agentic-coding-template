> Datenstand: {{DATUM}} – Status: Vorlage, noch nicht projektspezifisch

# Dokumentations-Index — {{PROJEKTNAME}}

Zweck: eine Sitzung (Mensch oder Assistent) soll in wenigen Minuten ein vollständiges, belastbares Bild des
Projekts bekommen. Tabelle statt Fließtext, damit man ohne Öffnen jeder Datei weiß, was drinsteht.

## Reihenfolge zum Einlesen

1. `README.md` (Repo-Root) — Einstieg, Schnellstart, Ordnerübersicht.
2. `AGENTS.md` (Repo-Root) — werkzeugunabhängige Grundregeln.
3. `docs/ai/board.md` — aktueller Stand, nächster Schritt.
4. Diese Tabelle — je nach Aufgabe gezielt die passende Datei.

## Index

| Datei | Inhalt (Kurzfassung) | Datenstand | Wann lesen |
| :--- | :--- | :--- | :--- |
| `docs/project/project_description.md` | Ziel, Nutzer, Scope/Non-Scope, Erfolgskriterien | {{DATUM}} | vor Umsetzung |
| `docs/project/architecture.md` | Schichten, Datenfluss, Schnittstellen | {{DATUM}} | vor größeren Umbauten |
| `docs/project/coding_rules.md` | Stil-, Sprach- und Typisierungsregeln | {{DATUM}} | vor jeder Code-Änderung |
| `docs/project/testing.md` | Testpyramide, Pflichtläufe, ungetestete Bereiche | {{DATUM}} | vor/nach Tests |
| `docs/project/features.md` | Feature-Liste mit Status und Beleg | {{DATUM}} | vor neuen Features |
| `docs/project/decisions.md` | Architekturentscheidungen (ADRs) | {{DATUM}} | vor Architektur-Entscheidungen |
| `docs/project/setup.md` | Einrichtung, Befehle, Umgebungsvariablen (Namen) | {{DATUM}} | beim ersten Einrichten |
| `docs/project/deployment.md` | Zielumgebung, Ablauf, Konfiguration | {{DATUM}} | vor einem Deployment |
| `docs/project/security.md` | Secrets-Regeln, Freigaben, Risiko-Liste | {{DATUM}} | vor Sicherheits-Änderungen |
| `docs/project/glossary.md` | Fachbegriffe des Projekts | {{DATUM}} | bei Unklarheit über Begriffe |
| `docs/project/incidents/README.md` | Schema für schwere Fehleranalysen | {{DATUM}} | vor/nach Fehleranalyse |
| `docs/ai/README.md` | Aufbau/Formregeln des Zusammenarbeits-Ordners | {{DATUM}} | vor Nutzung von `docs/ai/` |
| `docs/ai/board.md` | Einstiegs-/Wiedereinstiegsboard | {{DATUM}} | immer zuerst |
| `docs/ai/tasks.md` | Aufgabenliste inkl. Tabu-Abschnitt | {{DATUM}} | vor jeder neuen Aufgabe |
| `docs/ai/tasks_archive.md` | Erledigte Aufgaben im Volltext | {{DATUM}} | bei Bedarf nachschlagen |
| `docs/ai/questions.md` / `questions_archive.md` | Offene/archivierte Fragen | {{DATUM}} | nach jeder Antwort |
| `docs/ai/ledger.md` | Sitzungsjournal mit Belegen | {{DATUM}} | zur Historie/Übergabe |
| `docs/ai/backlog.md` | Priorisierte Verbesserungsvorschläge | {{DATUM}} | vor größeren Umbauten |
| `docs/ai/checklists.md` | Werkzeugneutrale Arbeitsanweisungen | {{DATUM}} | vor der jeweiligen Aktion |

## Konventionen für diese Doku

- Datenstände immer mit **Datum** kennzeichnen (Format `YYYY-MM-DD`), Kopfzeile jeder Datei: „Datenstand: … –
  Status: …".
- Verifiziert vs. Annahme klar trennen: Annahmen mit **(Annahme)** markieren.
- Secrets (Passwörter, Token, Schlüssel) **niemals** im Klartext ablegen — nur Verweise/Platzhalter. Ablageort:
  `.env`/`.mcp.json` (beide gitignored, sobald echte Werte eingetragen sind).
- `docs/project/` beschreibt den IST-Zustand, nicht den Wunsch — Wünsche/Vorschläge gehören auf
  `docs/ai/backlog.md`.
