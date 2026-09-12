# Coding-Regeln — Tailwind CSS

Regeln für Utility-First-Styling mit Tailwind, meist innerhalb eines Frontend-Frameworks.

## Sprache und Stil
- Utility-Klassen direkt im Markup verwenden, keine eigenen CSS-Dateien ohne konkreten Grund.
- Klassenreihenfolge konsistent halten (Layout, Box-Modell, Typografie, Farbe, Zustand) — per Formatter-Plugin
  erzwingen statt von Hand zu sortieren.
- Design-Tokens (Spacing-, Farb-, Radius-Skala aus der Konfiguration) statt beliebiger Zahlenwerte
  (`p-[13px]` nur in begründeten Ausnahmen).

## Struktur
- Wiederkehrende Klassenkombinationen als Komponente/Partial extrahieren, nicht als Text-Snippet kopieren.
- Theme-Anpassungen (Farben, Schriften, Breakpoints) zentral in der Tailwind-Konfiguration, nicht verstreut.

## Varianten und Zustände
- Dark-Mode über die konfigurierten Design-Tokens/Varianten abbilden, keine parallelen Hardcoded-Farbwerte.

## Werkzeuge
- Linter/Formatter: `prettier-plugin-tailwindcss` für automatische Klassensortierung.

## Fallstricke
- `@apply` nur in Ausnahmefällen (z. B. Basis-Stile von Drittkomponenten), nicht als Standardweg für Styling.
- Unbenutzte Utility-Klassen durch korrekte `content`-Pfade in der Konfiguration aus dem Build fernhalten.
