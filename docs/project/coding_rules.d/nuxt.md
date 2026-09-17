# Coding-Regeln — Nuxt

Regeln für Nuxt-Projekte: Verzeichniskonvention, Datenzugriff, sichere Konfiguration.

## Sprache und Stil
- Verzeichniskonvention einhalten (`pages/`, `components/`, `composables/`, `server/`) statt eigener Struktur.
- Auto-Imports nutzen, keine manuellen Re-Exports für Dateien in den Standardverzeichnissen.

## Struktur
- `useFetch`/`useAsyncData` zum Lesen von Daten beim Rendern, `$fetch` für einmalige Schreibzugriffe/Aktionen.
- **Rückgabe von `useFetch`/`useAsyncData` nie in ein eigenes `ref` umkopieren** — direkt weiterreichen und, wo
  `data`/`status`/`error` im Template landen, `await`-en. Beim Umkopieren geht die Awaitability verloren: der
  Aufruf läuft sofort durch, der Server rendert ohne Daten, der Client füllt sie nach — Ergebnis ist ein
  Hydration-Mismatch.

  ```ts
  // Falsch — Awaitability geht verloren
  function useThing() {
    const result = ref()
    useFetch('/api/thing').then(r => (result.value = r.data.value))
    return result
  }

  // Richtig — Rückgabeobjekt unverändert durchreichen
  async function useThing() {
    return await useFetch('/api/thing')
  }
  ```
- Server-Routen unter `server/api/` mit Verb-Suffix benennen (`login.post.ts`, `users.get.ts`).
- **Feste Ordner im Repo-Root, je mit eigenem Alias** — jeweils die einzige Ablage ihrer Art, keine zweite
  Fassung unterhalb von `app/`:

  | Ordner | Alias | Inhalt |
  | :--- | :--- | :--- |
  | `/types` | `~types` | geteilte Typen und Schnittstellen |
  | `/constants` | `~constants` | Konstanten, Aufzählungen, feste Schlüssel |
  | `/server` | `~server` | Nitro-Backend |

  Die Aliasse gehören in `tsconfig.json` **und** `nuxt.config.ts` (Nuxts `~` zeigt ab Nuxt 4 auf `app/` —
  ohne eigenen Eintrag zeigt `~/types` deshalb woanders hin als `~types`). Typen und Konstanten werden von
  dort importiert, nicht in Komponenten dupliziert; ein zweiter Typ-Ordner unter `app/types/` ist ein Fehler,
  keine Ergänzung.

## Typisierung / Fehlerbehandlung
- **Strikt typisieren.** `strict` und `noImplicitAny` sind gesetzt; Props, Emits, Store-Aktionen, Composables
  und `defineEventHandler` bekommen ausgeschriebene Typen samt Rückgabetyp. Kein `any`, keine stillen Casts.
- **Grenze der Strenge:** Wird ein Typ so verschachtelt, dass er schwerer zu lesen ist als der Code, den er
  beschreibt (tief verschachtelte Generics, mehrfach bedingte Typen, ausgereizte Mapped Types), ist ein
  bewusst einfacherer Typ die bessere Wahl — dann `unknown` mit Prüfung an der Grenze oder ein schmales
  `interface` für genau die benutzten Felder, mit einer Zeile Kommentar, warum. Diese Ausnahme gilt der
  Lesbarkeit, nicht der Bequemlichkeit: `any` bleibt auch hier ausgeschlossen.
- `runtimeConfig` für Konfigurationswerte verwenden, kein direkter Zugriff auf `process.env` in Komponenten.
- Secrets ausschließlich im privaten Teil von `runtimeConfig`, niemals unter `public`.
- Fehler aus `server/api`-Routen mit `createError` und passendem HTTP-Status zurückgeben.

## Werkzeuge
- **Pflichtausstattung, kein Merkmal einzelner Projekte:** Lint, Typecheck, Unit-Tests und E2E-Tests müssen
  in jedem Nuxt-Projekt vorhanden sein und laufen. Fehlt eines, ist das ein Mangel, keine Projekteigenheit.
- Linter/Formatter: ESLint mit `@nuxt/eslint`, Konfiguration `eslint.config.mjs`; Prettier für Formatierung.
- Typecheck: `vue-tsc` als Abhängigkeit — **ohne das Paket gibt es keinen Typecheck**, `nuxt typecheck` läuft
  sonst nicht.
- Unit-/Komponententests: `vitest`, Konfiguration `vitest.config.ts`.
- E2E-Tests: `@playwright/test`, Konfiguration `playwright.config.ts`.
- Feste npm-Scripts, damit die Befehle überall gleich heißen: `lint` (`eslint .`), `typecheck`
  (`nuxt typecheck`), `test` (`vitest run`), `test:e2e` (`playwright test`).

## Fallstricke
- SSR-Code darf nicht auf browserspezifische Globals (`window`, `document`) ohne Guard zugreifen.
- `<ClientOnly>` nur, wenn eine Komponente wirklich nicht serverseitig rendern kann, nicht als Standardlösung.
- **Sicherheitsrelevant:** Kein modulweites `ref`/`reactive` für Zustand, der pro Anfrage gilt. Auf dem
  Server lebt ein solcher Wert über alle Anfragen hinweg und wird zwischen Nutzern geteilt — die nächste
  Anfrage bekommt die Daten der vorigen. Für Zustand, der über den Request hinaus geteilt werden soll, immer
  `useState` verwenden.
- Formulare mit `@submit.prevent` brauchen zusätzlich `method="post"` — sicherheitsrelevant bei SSR, siehe
  `vue.md` § Fallstricke.
- **Windows:** Ein abgebrochener Dev-Server hält seinen Port teils weiter belegt; der nächste Start weicht auf
  den nächsten freien Port aus und danach kommt es zu HMR-/WebSocket-Fehlern (falscher Port in der
  Browser-Verbindung). Kein Konfigurationsfehler, sondern der belegte Port — Abhilfe ist der laufende Prozess
  beenden, nicht ein eigener HMR-Port:

  ```sh
  # Windows (PowerShell/cmd)
  netstat -ano | findstr :3000
  taskkill /PID <pid> /F

  # Linux/macOS
  lsof -i :3000
  kill <pid>
  ```
- Setzt zusätzlich `vue` und `typescript` voraus.
