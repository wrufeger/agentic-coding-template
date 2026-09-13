---
name: design-assets
description: Grafiken für das Projekt erzeugen - Logo, Icon-Satz, Illustration, Favicons - als SVG von Hand oder per Bildmodell, geprüft und ins Repo gelegt. Auslöser - "/design-assets", "Logo entwerfen", "Icons für X", "Favicon erzeugen", "Produktbild".
---

# Grafiken erzeugen

Erzeugt Bilddateien, die im Projekt bleiben: Logo, Icon-Satz, Illustration, Favicons, Platzhalterbilder.
Anders als `/design-ideas` (Wegwerf-Varianten zur Diskussion) landet das Ergebnis hier **im Repo**.

## Zuerst: Welcher Weg?

**Claude erzeugt keine Rasterbilder.** Es ist ein Text- und Code-Modell, kein Bildmodell — es kann Bilder
lesen, aber keine malen. Daraus folgen zwei Wege:

| Was gebraucht wird | Weg | Voraussetzung |
| :--- | :--- | :--- |
| Logo, Icon, Symbol, Diagramm, geometrische Illustration | **SVG, von Claude geschrieben** | keine — das ist Code |
| Foto, Produktbild, fotorealistische Szene, gemalte Illustration | **Bildmodell über MCP** | ein konfigurierter Server (`AI-CONFIG.md` § `MCP-Server`), kostet je Bild |

Fehlt für den zweiten Fall der Server, ist die richtige Antwort: sagen, dass es ohne Bildmodell nicht geht,
und die Kandidaten aus `.claude/mcp-katalog.md` nennen — **nicht** ersatzweise ein SVG liefern, das aussieht
wie ein Platzhalter, und es Produktbild nennen.

## Vor einem Logo: die Rechtefrage

Bevor ein Logo entsteht, gehört das einmal gesagt und die Antwort in einem ADR festgehalten:

- **Rein KI-generierte Werke sind nicht automatisch urheberrechtlich geschützt.** Das US Copyright Office
  verlangt einen menschlichen Schöpfungsanteil. Ein Logo, an dem keine Rechte bestehen, kann jeder
  verwenden — für eine Marke ist das ein echtes Problem, für ein internes Symbol meist keins.
- **Die Anbieter unterscheiden sich.** Bei manchen Bildmodellen sind kommerzielle Nutzung und
  Rechteübertragung ausdrücklich geregelt, bei anderen hängt es an der Modellvariante (nicht-kommerzielle
  „Dev"-Lizenz gegen kommerzielle). Adobe Firefly wirbt mit Freistellung bei Rechtsansprüchen — bei einem
  Logo ist das der praktisch relevante Unterschied.
- **Ein SVG von Claude ist derselben Frage ausgesetzt**, aber leichter zu entschärfen: Wer den Entwurf
  bearbeitet, ändert und auswählt, bringt den menschlichen Anteil ein.

Für ein Logo, das eine Marke tragen soll, ist die ehrliche Empfehlung: als Entwurfsgrundlage nutzen, die
Endfassung von einem Menschen gestalten lassen.

## Ablauf für SVG (Logo, Icons, Illustration)

1. **Auftrag klären:** Was, wofür, welche Stimmung, welche Farben (Tokens des Projekts nutzen, nicht neu
   erfinden), welche Größen. Bei Icons: Wie viele, welches Raster (16/24/32 px), Strich oder Fläche?
2. **Bestand prüfen:** Gibt es schon ein Icon-Set im Projekt (`@nuxt/icon`, Heroicons, Lucide …)? Dann wird
   **nichts neu gezeichnet**, was es dort gibt — nur, was fehlt, und im selben Stil (Strichstärke, Raster,
   Ecken).
3. **Zwei bis drei Entwürfe** als SVG, sichtbar unterschiedlich. Regeln: `viewBox` gesetzt, keine festen
   `width`/`height` am Wurzelelement, Farben über `currentColor` wo möglich (dann folgt das Icon der
   Textfarbe), keine eingebetteten Rasterbilder, keine Schrift als Text (Pfade, sonst fehlt der Font).
4. **Ansehen und prüfen** — nicht raten, ob es gut aussieht:
   - Playwright-Screenshot je Entwurf, **hell und dunkel**, in den Zielgrößen (ein Icon, das bei 16 px
     verschmiert, ist unbrauchbar, auch wenn es bei 512 px gut aussieht).
   - Auf Kontrast prüfen, wenn es auf farbigem Grund liegt.
5. **Auswahl durch {{AUFTRAGGEBER}}**, dann optimieren: SVGO oder gleichwertig (spart typischerweise
   deutlich an Dateigröße, ohne dass man es sieht). Danach erneut ansehen — Optimierer verändern gelegentlich
   die Darstellung.
6. **Ablegen** nach Projektkonvention (`public/`, `assets/`, `app/assets/`) und einbinden. Favicons als
   **Satz** erzeugen, nicht als Einzeldatei: 16, 32, 180 (Apple-Touch), 512 (PWA), dazu die Einträge in
   `nuxt.config.ts` bzw. dem Äquivalent.

## Ablauf für Rasterbilder (Bildmodell)

1. **Prüfen, ob ein Bildgenerator konfiguriert ist** (`AI-CONFIG.md` § `MCP-Server`, Katalog in
   `.claude/mcp-katalog.md`). Wenn nein: sagen, welche Kandidaten es gibt, dass Kosten je Bild anfallen und
   dass die Lizenzbedingungen vor der Nutzung zu klären sind. Ohne Zusage nichts einrichten.
2. **Kosten und Rechte vorher benennen**, nicht hinterher.
3. Prompt aus dem Auftrag bauen, zwei bis vier Varianten erzeugen, zur Auswahl stellen.
4. **Nachbearbeiten:** auf die Zielgröße bringen, als WebP oder AVIF speichern (PNG nur als Rückfall),
   Dateigröße prüfen. Ein Produktbild mit 4 MB gehört nicht ins Repo.
5. Herkunft festhalten: welches Modell, welcher Prompt, welches Datum — in `docs/project/decisions.md` oder
   einer Textdatei neben dem Bild. Ohne diese Angabe ist später nicht mehr feststellbar, unter welchen
   Bedingungen das Bild entstanden ist.

## Grenzen

- **Große Rohdateien gehören nicht ins Repo.** PSD, AI, unkomprimierte PNG lassen Git binär anwachsen und
  sind nicht diffbar. Wenn sie aufbewahrt werden müssen: außerhalb oder per Git-LFS, bewusst entschieden.
- **Kein Fotorealismus aus SVG.** Wer das versucht, produziert eine 400-KB-Datei, die schlechter aussieht als
  ein 20-KB-WebP.
- **Keine fremden Marken nachbauen.** Ein Logo „im Stil von" einer bekannten Marke ist kein Entwurf, sondern
  ein Rechtsproblem.
- Der Skill entscheidet nicht über Gestaltung. Er liefert Entwürfe und Belege; die Auswahl trifft
  {{AUFTRAGGEBER}}.
