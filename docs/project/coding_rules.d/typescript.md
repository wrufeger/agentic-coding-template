# Coding-Regeln — TypeScript

Regeln für TypeScript im strict-Modus mit zentraler Typablage und sauberem Narrowing.

## Sprache und Stil
- `strict: true` in der `tsconfig.json`, keine punktuellen Lockerungen ohne Begründung im Code-Kommentar.
- `any` ist verboten — unbekannte Werte als `unknown` typisieren und vor Verwendung schmälern (Narrowing).
- `interface` für Objektformen/Verträge, `type` für Unions, Intersections und abgeleitete Typen.
- Enums vermeiden — stattdessen `as const`-Objekte oder Union-Literaltypen.

## Struktur
- Gemeinsam genutzte Typen/Schemas an einer zentralen Stelle definieren und importieren, nicht je Modul neu
  deklarieren.
- Öffentliche Modul-Exporte über einen expliziten Index, keine tiefen Importpfade in fremde Module.

## Typisierung / Fehlerbehandlung
- Rückgabetypen an exportierten Funktionen explizit angeben, nicht auf Inferenz verlassen.
- Typ-Assertions (`as Type`) nur, wenn kein Narrowing möglich ist, und mit Kommentar begründet.
- Fehler als typisierte Result- oder Error-Objekte weiterreichen, kein `throw` beliebiger Werte.

## Werkzeuge
- Linter/Formatter: ESLint mit `@typescript-eslint`, Prettier für Formatierung.

## Fallstricke
- Non-null-Assertion (`!`) vermeiden — sie unterdrückt echte Nullable-Prüfungen.
- Generics nur einführen, wenn mehr als eine konkrete Verwendung ansteht, sonst konkreter Typ.
