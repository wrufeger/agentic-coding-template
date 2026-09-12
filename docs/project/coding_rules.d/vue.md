# Coding-Regeln — Vue 3

Regeln für Vue-3-Komponenten mit Composition API und `<script setup>`.

## Sprache und Stil
- `<script setup lang="ts">` in jeder Komponente, keine Options-API in neuem Code.
- Reihenfolge im SFC: `<script setup>`, `<template>`, `<style>`.
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
- Setzt zusätzlich `typescript` voraus.
