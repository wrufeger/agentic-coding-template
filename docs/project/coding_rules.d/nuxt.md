# Coding-Regeln — Nuxt

Regeln für Nuxt-Projekte: Verzeichniskonvention, Datenzugriff, sichere Konfiguration.

## Sprache und Stil
- Verzeichniskonvention einhalten (`pages/`, `components/`, `composables/`, `server/`) statt eigener Struktur.
- Auto-Imports nutzen, keine manuellen Re-Exports für Dateien in den Standardverzeichnissen.

## Struktur
- `useFetch`/`useAsyncData` zum Lesen von Daten beim Rendern, `$fetch` für einmalige Schreibzugriffe/Aktionen.
- Server-Routen unter `server/api/` mit Verb-Suffix benennen (`login.post.ts`, `users.get.ts`).
- Geteilte Typen/Utilities unter `shared/` oder `utils/` ablegen, nicht in Komponenten duplizieren.

## Typisierung / Fehlerbehandlung
- `runtimeConfig` für Konfigurationswerte verwenden, kein direkter Zugriff auf `process.env` in Komponenten.
- Secrets ausschließlich im privaten Teil von `runtimeConfig`, niemals unter `public`.
- Fehler aus `server/api`-Routen mit `createError` und passendem HTTP-Status zurückgeben.

## Werkzeuge
- Linter/Formatter: ESLint-Konfiguration von Nuxt (`@nuxt/eslint`), Prettier für Formatierung.

## Fallstricke
- SSR-Code darf nicht auf browserspezifische Globals (`window`, `document`) ohne Guard zugreifen.
- `<ClientOnly>` nur, wenn eine Komponente wirklich nicht serverseitig rendern kann, nicht als Standardlösung.
- Setzt zusätzlich `vue` und `typescript` voraus.
