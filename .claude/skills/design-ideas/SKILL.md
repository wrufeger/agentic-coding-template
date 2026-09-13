---
name: design-ideas
description: Drei bis vier Design-Varianten als Vorschaubilder erzeugen, aus Beschreibung, Screenshots oder Weblinks - zur Diskussion, bevor Code entsteht. Auslöser - "/design-ideas", "Entwürfe zeigen", "Varianten für <Komponente/Seite>", "wie könnte X aussehen".
---

# Design-Varianten zur Auswahl

Erzeugt **drei bis vier** sichtbar unterschiedliche Entwürfe für eine Komponente oder Seite und legt sie als
Bilder ab, über die sich reden lässt. Danach entscheidet {{AUFTRAGGEBER}}, und erst dann wird gebaut
(`/design-build`).

**Warum Bilder und nicht Beschreibungen:** Über „luftiger" oder „moderner" lässt sich endlos reden. Über zwei
Screenshots nebeneinander dauert dieselbe Entscheidung zehn Sekunden.

## Voraussetzungen

Prüfe zuerst, **womit** die Bilder entstehen können — in dieser Reihenfolge:

1. **Playwright im Projekt** (`playwright.config.*` oder `@playwright/test` in `package.json`): der Normalfall.
   Braucht einmalig `npx playwright install` für die Browser.
2. **Claude in Chrome**: geht auch, ist aber langsamer und weniger reproduzierbar.
3. **Nichts davon**: keine Bilder möglich. Dann **nicht** ersatzweise Beschreibungen liefern und es Entwurf
   nennen — sag, dass Vorschaubilder Playwright brauchen, und biete an, es einzurichten (`docs/project/coding_rules.d/nuxt.md` § Werkzeuge).

## Ablauf

1. **Auftrag klären** (kurz, im Gespräch — höchstens diese vier Punkte):
   - Was genau: eine Komponente, eine ganze Seite, ein Ausschnitt?
   - Wofür: welcher Zweck, welche Inhalte, welche Nutzergruppe?
   - Vorlagen: Beschreibung, Screenshot (Pfad), Weblink, vorhandene Seite im Projekt?
   - Bandbreite: soll sich alles am Bestand orientieren oder ausdrücklich auch etwas Ungewohntes dabei sein?
2. **Vorlagen einlesen:**
   - **Screenshots**: Bilddatei direkt lesen. Grenzen beachten (JPEG/PNG/GIF/WebP, max. 8000 × 8000 px und
     10 MB; unter 200 px Kantenlänge unbrauchbar).
   - **Weblinks**: Seite in Claude in Chrome öffnen und Screenshot speichern. **Nicht** `WebFetch` — das
     liefert HTML als Text, nicht das Aussehen.
   - Bei jeder Vorlage nachfragen, **was** daran gefällt, falls es nicht dabeisteht. „Die Kartenabstände" ist
     brauchbar, „sieht gut aus" nicht.
3. **Bestand lesen, bevor etwas Neues entsteht** (Sub-Agent `explorer`, Sonnet): Welche Komponentenbibliothek,
   welche Farb- und Abstands-Tokens, welche vergleichbaren Seiten gibt es schon? Ein Entwurf, der die
   vorhandenen Bausteine ignoriert, ist später teuer. Ergebnis ≤ 20 Zeilen.
4. **Varianten bauen.** Je Variante eine eigenständige HTML-Datei unter `.design-varianten/` (gitignored,
   Wegwerfware) — mit **echten Projektmitteln**: dieselbe CSS-Bibliothek, dieselben Tokens, echte
   Beispieldaten aus dem Projekt statt „Lorem ipsum". Die Varianten müssen sich in etwas Erkennbarem
   unterscheiden (Aufbau, Dichte, Hierarchie), nicht nur in Farbnuancen. Je Variante eine Zeile Begründung:
   worin sie sich unterscheidet und für wen sie spricht.
   Sind die Varianten unabhängig voneinander, parallel von je einem `builder` (Sonnet) bauen lassen.
5. **Screenshots erzeugen** — je Variante mindestens Desktop (1280 px) und Mobil (390 px). Playwright headless
   gegen die lokalen HTML-Dateien; kein Dev-Server nötig.
6. **Übersicht ablegen:** `.design-varianten/uebersicht.html` mit allen Screenshots nebeneinander, je mit
   Nummer und der Begründung aus Schritt 4. Den Dateipfad im Chat nennen — im Terminal sind Bilder nicht
   sichtbar, die Datei wird im Browser geöffnet.
7. **Zur Entscheidung stellen:** die Varianten mit je einem Satz vorstellen und **eine** Frage stellen:
   „Welche Richtung? a) 1 b) 2 c) 3 d) Mischung — welche Teile?" Keine Empfehlung als Vorentscheidung
   verkaufen; eine begründete Präferzung nennen ist in Ordnung, mehr nicht.
8. **Ergebnis sichern:** Die gewählte Richtung samt Begründung in einem Satz nach `docs/project/decisions.md`
   (ADR), wenn sie über den Einzelfall hinaus gilt — etwa „Listen künftig als Karten, nicht als Tabelle".
   Sonst genügt der Auftrag an `/design-build`.

## Grenzen

- **Kein Code im Projekt.** Dieser Skill schreibt ausschließlich nach `.design-varianten/`. Die Umsetzung
  macht `/design-build`.
- **Höchstens vier Varianten.** Mehr wird nicht besser, sondern unentscheidbar.
- `.design-varianten/` gehört in `.gitignore`. Wird eine Variante wichtig, wandert ihr Screenshot bewusst als
  Datei ins Repo — nicht der ganze Ordner.
- Läuft **nicht** in einem Sub-Agenten als Ganzes: Die Rückfragen in Schritt 1 und 7 gehören in den
  Hauptkontext. Das Bauen der einzelnen Varianten wird delegiert.
