> Datenstand: {{DATUM}} – Status: Vorlage, noch nicht projektspezifisch

# Konzepte — {{PROJEKTNAME}}

Entscheidungsgrundlagen. Ein Konzept beschreibt **einen** Bereich, vergleicht die Optionen, gibt eine
begründete Empfehlung und beziffert den Aufwand. Es ist der Ort für alles, was zu lang für eine Aufgabe, zu
unentschieden für ein ADR und zu umfangreich für einen Backlog-Punkt ist: Analysen, Abwägungen, Umbaupläne,
Migrationsumfänge.

**Warum dieser Ordner existiert:** Ohne ihn landen solche Papiere als freie Dateien in `docs/ai/` — und dort
ist alles flüchtig (Aufgaben werden archiviert, Fragen beantwortet, das Board überschrieben). Ein Konzept
zwischen Arbeitsdateien wird beim nächsten Aufräumen entweder mitentsorgt oder bleibt als Fremdkörper zurück,
den keine Checkliste je wieder prüft.

Abgrenzung zu den Nachbarn:

| Ort | Inhalt |
| :--- | :--- |
| `../architecture.md` und die übrigen Dateien in `../` | **IST-Zustand** des Projekts |
| dieser Ordner | **Überlegung dazwischen** — Optionen, Empfehlung, Aufwand |
| `../stories/` | **umsetzbare Schritte** mit Abnahmebedingung |
| `../decisions.md` | die **getroffene Entscheidung** als ADR, in wenigen Zeilen |

Ein Konzept ersetzt kein ADR: Sobald entschieden ist, wird das Ergebnis als ADR verbucht; das Konzept bleibt
als Begründung liegen und bekommt im Kopf den Verweis darauf.

## Format

Dateiname `<thema>.md`, Kleinbuchstaben mit Bindestrich. Kopfzeile wie überall in `docs/`
(`> Datenstand: … – Status: …`), als Status hier `Entwurf` → `abgestimmt` → `umgesetzt`; ein durch eine
spätere Entscheidung überholtes Konzept wird `veraltet — abgelöst durch ADR-<n>`. Aufbau:

```text
# <Thema>

**Leitfrage:** die eine Entscheidung, um die es geht (mit Verweis `Q<n>`, falls gestellt).
**Aufwand:** Schätzung, Einheit nennen.

## Ausgangslage
Was heute da ist, mit Kennzahlen und Fundstellen.

## Optionen
Je Option: Beschreibung, Vorteile, Nachteile, Aufwand.

## Empfehlung
Eine Option, begründet in wenigen Sätzen.

## Offene Punkte
Was noch entschieden werden muss — jeweils als Frage in `../../ai/questions.md` gestellt, hier nur verwiesen.
```

## Vorhandene Konzepte

*(noch keine — Tabelle Thema · Inhalt · Leitfrage · Aufwand pflegen, sobald das erste Konzept entsteht)*
