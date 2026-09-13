> Datenstand: 2026-09-14 – Status: aktuell

# Testprojekte

Übersicht des Arbeitsordners: `INDEX.md`.

Das Template lässt sich am eigenen Repo kaum prüfen: Dort gibt es keinen Anwendungscode, keinen fremden
Verzeichnisbaum, keine gewachsene Historie und keine Altlasten. Fehler zeigen sich erst am echten Einsatz.
Deshalb gibt es benannte Testprojekte — reale Anwendungen, an denen ein Weg des Templates **offiziell**
durchgespielt wird und deren Befunde hierher zurückfließen.

Der Stand unten wird von `python .claude/scripts/testprojekte.py --update` geschrieben; `--check` vergleicht
ihn mit dem, was in den Projekten tatsächlich liegt, ohne etwas zu ändern.

<!-- testprojekte:start -->
| Projekt | Pfad | Weg | Letzter geprüfter Commit | Stand |
| :--- | :--- | :--- | :--- | :--- |
| Bandliste | `D:\dev\rufeger\bandliste` | Weg 2 — bestehendes Projekt nachrüsten | `4d348ac` (2026-09-13) | Arbeitsbaum sauber, 64 Commits ungepusht |
<!-- testprojekte:end -->

**Bandliste** (Nuxt 4 + Prisma, dazu rund 49.000 Dateien PHP-Altanwendung in `old-project/`) ist das
Referenzprojekt für das **Nachrüsten** (Weg 2). Es dient ausdrücklich auch als Prüfstand für die
Zusammenarbeit mit der KI selbst: Was dort an Reibung auftritt — missverstandene Aufträge, unpassende Regeln,
fehlende Automatisierung, entgleiste Worker-Läufe —, ist ein Befund über das Template und wird als Umbaupunkt
aufgenommen, nicht nur im Projekt behoben.

**Template-Entwicklung** (dieses Projekt) ist das Referenzprojekt für **Neues Projekt** (Weg 1): Es ist selbst
per `/create-project` aus dem Template entstanden und zieht Template-Änderungen per `/update-template` nach.
Was hier beim Arbeiten stört, ist ebenfalls ein Befund über das Template — siehe
`docs/project/architecture.md` § Kreislauf.

Die Commits der Testprojekte liegen bislang **nur lokal**; der Hash oben ist damit die einzige belastbare
Referenz auf einen Stand. Wird ein Testprojekt später gepusht, gehört sein Remote mit in die Tabelle.

## Regel

Ein Fehler, der beim Einsatz in einem Testprojekt auffällt, wird **im Projekt** behoben (damit es weitergeht)
**und** hier — bzw. in `docs/ai/` dieses Projekts — als Befund verbucht, wenn die Ursache im Template liegt.
Nur im Projekt reparieren heißt: Das nächste Projekt tritt in dieselbe Grube. Eine Template-Änderung ist erst
dann wirklich belegt, wenn sie am zuständigen Testprojekt gelaufen ist — „im Wegwerf-Repo getestet" ist ein
Zwischenschritt, kein Ersatz (Details: `docs/project/template-pflege.md`).
