# Template-Entwicklung

Arbeitsordner für die Weiterentwicklung **dieses Template-Repos**. Er gehört nicht zum Lieferumfang: Beim
Anlegen eines Projekts wird er entfernt (`setup-lib.py`), beim Nachrüsten nie kopiert, und ein
Template-Update trägt ihn nicht in abgeleitete Projekte (`template_only` in `.claude/template.json`).

Warum nicht `docs/ai/`? Weil dort nur **Vorlagen** liegen: Board, Aufgaben, Fragen, Ledger und Umbauliste
sind im Template leere Gerüste, die jedes abgeleitete Projekt mit eigenen Inhalten füllt. Stünde die
Template-Entwicklung dort, wanderte sie in jedes Projekt mit. Dasselbe gilt für `docs/project/` — die
Beschreibung eines Projekts, das es hier nicht gibt.

| Datei | Inhalt | Versioniert |
| :--- | :--- | :--- |
| `README.md` | diese Übersicht, die Testprojekte und wie hier gearbeitet wird | ja |
| `regeln.md` | Regeln für die Arbeit **am Template selbst** | ja |
| `vorlagen/` | leere Gerüste der drei Arbeitsdateien | ja |
| `init.py` | legt fehlende Arbeitsdateien aus den Vorlagen an | ja |
| `testprojekte.py` | gleicht die Testprojekt-Tabelle mit dem echten Stand ab | ja |
| `backlog.md` | Umbauliste: priorisierte Verbesserungsvorschläge, Nummern bleiben stabil | **nein, lokal** |
| `questions.md` | offene Entscheidungen zur Weiterentwicklung (`T<n>`) | **nein, lokal** |
| `ledger.md` | Journal: was in welcher Sitzung passiert ist, mit Belegen | **nein, lokal** |
| `daten/` | Messwerte, Testprotokolle, Auswertungen — zu lang für den Fließtext | **nein, lokal** |

Die drei Arbeitsdateien und `daten/` sind gitignored: laufender Arbeitsstand, der lokal bleibt. Fehlen sie in
einem frischen Checkout, legt `python .templatedev/init.py --apply` sie aus den Vorlagen an — vorhandene
Dateien werden dabei nie überschrieben. Was das für die Sicherung bedeutet, steht in `regeln.md`
§ „Was versioniert ist und was nicht"; kurz: Es gibt keine.

## Testprojekte

Das Template lässt sich am eigenen Repo kaum prüfen: Hier gibt es keinen Anwendungscode, keinen fremden
Verzeichnisbaum, keine gewachsene Historie und keine Altlasten. Fehler zeigen sich erst am echten Einsatz.
Deshalb gibt es benannte Testprojekte — reale Anwendungen, an denen ein Weg **offiziell** durchgespielt wird
und deren Befunde hierher zurückfließen.

Der Stand unten wird von `python .templatedev/testprojekte.py --update` geschrieben; `--check` vergleicht ihn
mit dem, was in den Projekten tatsächlich liegt, ohne etwas zu ändern.

<!-- testprojekte:start -->
| Projekt | Pfad | Weg | Letzter geprüfter Commit | Stand |
| :--- | :--- | :--- | :--- | :--- |
| Bandliste | `D:\dev\rufeger\bandliste` | Weg 2 — bestehendes Projekt nachrüsten | `4d348ac` (2026-09-13) | Arbeitsbaum sauber, 64 Commits ungepusht |
<!-- testprojekte:end -->

**Bandliste** (Nuxt 4 + Prisma, dazu rund 49.000 Dateien PHP-Altanwendung in `old-project/`) ist das
Referenzprojekt für das **Nachrüsten**. Es dient ausdrücklich auch als Prüfstand für die Zusammenarbeit mit
der KI selbst: Was dort an Reibung auftritt — missverstandene Aufträge, unpassende Regeln, fehlende
Automatisierung, entgleiste Worker-Läufe —, ist ein Befund über das Template und wird als Umbaupunkt
aufgenommen, nicht nur im Projekt behoben.

Die Commits der Testprojekte liegen bislang **nur lokal**; der Hash oben ist damit die einzige belastbare
Referenz auf einen Stand. Wird ein Testprojekt später gepusht, gehört sein Remote mit in die Tabelle.

Ein Testprojekt für **Weg 1** („Neues Projekt") fehlt noch. Bis dahin ist dieser Weg nur durch Smoketests in
Wegwerf-Repos abgedeckt — das ist schwächer, siehe `regeln.md`.

## Wie hier gearbeitet wird

- Ein Fehler, der beim Einsatz auffällt, wird **im Projekt** behoben (damit es weitergeht) **und** hier als
  Punkt notiert, wenn die Ursache im Template liegt. Nur im Projekt reparieren heißt: Das nächste Projekt
  tritt in dieselbe Grube.
- Eine Template-Änderung ist erst dann wirklich belegt, wenn sie am Testprojekt gelaufen ist. „Im
  Wegwerf-Repo getestet" ist ein Zwischenschritt, kein Ersatz.
- Nummern in `backlog.md` und `questions.md` werden nie neu vergeben, auch nicht nach dem Erledigen.
