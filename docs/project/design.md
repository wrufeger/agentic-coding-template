> Datenstand: {{DATUM}} – Status: Vorlage, noch nicht projektspezifisch

# Design — {{PROJEKTNAME}}

Verzeichnis der UI-Entwürfe, die mit Claude Design (`/design`) entstanden sind. Nur relevant, wenn
`AI-CONFIG.md` § `Design` auf `ein` steht — sonst wird diese Datei beim Anlegen des Projekts entfernt.

**Warum es diese Liste gibt.** Ein Entwurf liegt als Artifact in der Cloud, nicht im Repo: Die Artboards
werden außerhalb des Projektverzeichnisses erzeugt, Versionen führt die Artifact-Historie, und aus Claude
Code heraus gibt es nur PNG- und PDF-Export. Ohne diese Liste verweist im Repo nichts auf die Entwürfe — nach
zwei Wochen weiß niemand mehr, dass es sie gibt oder welcher Stand gilt. Details und Voraussetzungen:
`CLAUDE.md` § Design.

## Entwürfe

| Entwurf | Zweck | Artifact-URL | Stand | Umsetzung |
| :--- | :--- | :--- | :--- | :--- |
| *(noch keine)* | | | | |

Spalten: **Zweck** in drei bis fünf Wörtern (welcher Screen, welche Seite). **Stand** ist das Datum der
letzten Änderung am Entwurf. **Umsetzung** sagt, wie weit der Code dem Entwurf folgt — `offen`,
`teilweise (<Datei>)` oder `umgesetzt (<Datei>)`.

## Was hier nicht hingehört

- **Der Entwurf selbst.** Er wird nicht ins Repo kopiert; ein PNG-Export ist eine Momentaufnahme, die
  veraltet, sobald jemand am Artifact weiterarbeitet. Wenn ein Bild gebraucht wird (etwa für eine
  Fehleranalyse), gehört es mit Datum in den Ordner der jeweiligen Doku, nicht hierher.
- **Design-Entscheidungen.** Warum eine Farbe, ein Raster oder ein Interaktionsmuster gewählt wurde, gehört
  nach `decisions.md` (ADR) — dort wird es auch dann gefunden, wenn der Entwurf längst überholt ist.
- **Stilregeln.** Abstände, Komponenten, Farbtokens stehen in `coding_rules.md` bzw. dem passenden Baustein
  unter `coding_rules.d/`. Diese Liste verzeichnet Entwürfe, sie ersetzt kein Design-System.
