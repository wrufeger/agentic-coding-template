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
| `docs/project/incidents/README.md` | Fehleranalyse als Einzeldatei (Standard) oder Unterordner ab ~5/Jahr | {{DATUM}} | vor/nach Fehleranalyse |
| `docs/project/concepts/README.md` | Konzepte: Optionen, Empfehlung, Aufwand — je Thema eine Datei | {{DATUM}} | vor größeren Umbauten |
| `docs/project/stories/README.md` | Stories: abgegrenzte, prüfbare Umsetzungsschritte `S<n>` | {{DATUM}} | vor der Umsetzung |
| `docs/ai/README.md` | Aufbau/Formregeln des Zusammenarbeits-Ordners | {{DATUM}} | vor Nutzung von `docs/ai/` |
| `docs/ai/config-guide.md` | Ausführliche Begründungen zu den Schlüsseln aus `AI-CONFIG.md` | {{DATUM}} | bei Unklarheit über einen Schalter |
| `docs/ai/board.md` | Einstiegs-/Wiedereinstiegsboard | {{DATUM}} | immer zuerst |
| `docs/ai/tasks.md` | Aufgabenliste inkl. Tabu-Abschnitt | {{DATUM}} | vor jeder neuen Aufgabe |
| `docs/ai/tasks_archive.md` | Erledigte Aufgaben im Volltext | {{DATUM}} | bei Bedarf nachschlagen |
| `docs/ai/questions.md` / `questions_archive.md` | Offene/archivierte Fragen | {{DATUM}} | nach jeder Antwort |
| `docs/ai/ledger.md` | Sitzungsjournal mit Belegen | {{DATUM}} | zur Historie/Übergabe |
| `docs/ai/backlog.md` | Priorisierte Verbesserungsvorschläge | {{DATUM}} | vor größeren Umbauten |
| `docs/ai/checklists.md` | Werkzeugneutrale Arbeitsanweisungen | {{DATUM}} | vor der jeweiligen Aktion |
| `docs/ai/resources.md` | Quellen zu Agentic Coding (Einstieg, Werkzeuge, News, Grenzen) | 2026-09-13¹ | zum Einlesen ins Thema |

¹ Diese Datei pflegt das Template, nicht das Projekt — der Stand ist deshalb der des Templates und
wird von `/act-update-template` nachgezogen, nicht beim Anlegen gesetzt.

**Datenstand ohne Kopfzeile:** Trägt eine Datei keine eigene `> Datenstand:`-Zeile (generierte Datei,
Fremdformat, sehr kurze Datei), bekommt ihr Eintrag hier eine hochgestellte Ziffer und darunter eine Fußnote
mit der Herkunft — etwa `2026-01-31¹` in der Datenstand-Spalte und darunter:
`¹ Stand aus dem letzten Doku-Audit; die Datei trägt keine eigene Kopfzeile.`
Ein leeres Feld ist nie zulässig: entweder ein echter Stand oder eine Fußnote, die sagt, woher er kommt.

## Konventionen für diese Doku

- Datenstände immer mit **Datum** kennzeichnen (Format `YYYY-MM-DD`), Kopfzeile jeder Datei:
  `> Datenstand: JJJJ-MM-TT – Status: <wort>`. Das Datum ist der Tag, an dem der Inhalt zuletzt **gegen die
  Wirklichkeit geprüft** wurde — nicht der Tag der letzten Textänderung. Als Status ist genau eines dieser
  drei Wörter erlaubt, optional gefolgt von einem erläuternden Halbsatz:

  | Status | Bedeutung |
  | :--- | :--- |
  | `aktuell` | Inhalt entspricht dem Stand am genannten Datum |
  | `Entwurf` | wird gerade geschrieben, noch nicht verbindlich |
  | `veraltet` | bekannt überholt; der Halbsatz sagt wodurch (z. B. „abgelöst durch ADR-<n>") |

  Eigene Lebenszyklen haben nur `concepts/` und `stories/` (`Entwurf` → `abgestimmt` → `umgesetzt`), je in
  der README des Ordners beschrieben. Im Template steht stattdessen „Vorlage, noch nicht projektspezifisch";
  diese Fassung ersetzt `.claude/scripts/setup-lib.py` beim Anlegen und Nachrüsten. Bleibt sie irgendwo
  stehen, ist das ein Fehler und gehört gemeldet.
- Jede Doku-Datei **soll** eine eigene Kopfzeile tragen. Wo das nicht geht (generierte Dateien, Fremdformate,
  sehr kurze Dateien), wird der Datenstand im Index stattdessen mit hochgestellter Ziffer und Fußnote
  gekennzeichnet — ein leeres Feld ist nie zulässig, entweder echter Stand oder Fußnote mit Herkunft.
- Verifiziert vs. Annahme klar trennen: Annahmen mit **(Annahme)** markieren.
- Secrets (Passwörter, Token, Schlüssel) **niemals** im Klartext ablegen — nur Verweise/Platzhalter. Ablageort:
  `.env`/`.mcp.json` (beide gitignored, sobald echte Werte eingetragen sind).
- `docs/project/` beschreibt den IST-Zustand, nicht den Wunsch — Wünsche/Vorschläge gehören auf
  `docs/ai/backlog.md`.
