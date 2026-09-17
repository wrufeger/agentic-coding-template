# Coding-Regeln — Vue 3

Regeln für Vue-3-Komponenten mit Composition API und `<script setup>`.

## Sprache und Stil
- `<script setup lang="ts">` in jeder Komponente, keine Options-API in neuem Code.
- Reihenfolge im SFC: `<template>`, `<script setup>`, `<style>`.
- `ref` für primitive/atomare Werte, `reactive` nur für zusammenhängende Objektzustände.
- Composables als eigene Funktion mit `useX`-Namenskonvention, wiederverwendbar über Komponenten hinweg.

## Struktur
- Props mit `defineProps<Interface>()` typisieren, Emits mit `defineEmits<...>()` — keine losen Objekt-Props.
- Keine Geschäftslogik im `<template>` — Berechnungen in `computed` oder Methoden auslagern.
- Globaler Zustand über ein dediziertes Store-Modul (z. B. Pinia), nicht über provide/inject für App-weite Daten.

## Typisierung / Fehlerbehandlung
- Rückgabetyp von Composables explizit angeben, wenn er nicht trivial aus dem Rumpf ableitbar ist.
- Watcher/Effects mit klarer Cleanup-Funktion, wenn sie Ressourcen (Timer, Listener) binden.

## Werkzeuge
- Linter/Formatter: ESLint mit `eslint-plugin-vue`, Prettier für Formatierung.

## Fallstricke
- `v-if` und `v-for` nicht auf demselben Element kombinieren.
- Direkte Mutation von Props vermeiden — Änderungen über Events an die Elternkomponente melden.
- **Sicherheitsrelevant:** Formulare mit `@submit.prevent` brauchen zusätzlich `method="post"` auf dem
  `<form>`-Element. Der Handler existiert erst nach Abschluss der Hydration; ein Submit vor diesem Zeitpunkt
  (Passwort-Manager mit Enter, langsame Verbindung, blockiertes JS-Bundle) löst den nativen Browser-Submit
  aus. Ohne `method` ist das ein GET auf die aktuelle URL — bei Formularen mit Zugangsdaten landen die Werte
  in Adresszeile, Browser-Historie und Server-Log. Gilt für jede serverseitig gerenderte Anwendung, nicht nur
  für Auth-Formulare (Beleg: GHSA-gj2h-2fpw-fhv9, derselbe Fehler in `@nuxt/ui` vor Version 4.8.1).
- Setzt zusätzlich `typescript` voraus.
