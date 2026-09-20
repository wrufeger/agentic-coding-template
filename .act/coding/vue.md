# Coding rules — Vue

summary: composition API, typed props, SFC order, shared state, tooling
requires: typescript

Rules for Vue 3 components using the Composition API. Group IDs (`CR-vue-<name>`) are stable and
never reassigned; a group whose purpose no longer holds gets a new ID and is listed as `retired:` in
this header.

## `CR-vue-basics` — Composition API, typed props, safe forms

summary: script setup, typed props/emits, conventions, error handling, pitfalls

- Use `<script setup lang="ts">` in every component; no Options API in new code.
- Type `defineProps<...>()` and `defineEmits<...>()` — no loose object props.
- Keep no business logic in the `<template>` — move computations into `computed` or a method.
- Choose `ref` for primitive/atomic values, `reactive` only for one connected object state.
- Give composables a `useX` name and an explicit return type when it is not trivially inferred.
- Clean up a watcher/effect that binds a resource (timer, listener) once it is no longer needed.
- Catch errors around calls in components and composables on purpose: surface them where the
  template can show them, or rethrow — never swallow one silently; the message names what failed
  and with what. Use `onErrorCaptured` to handle a child component's error deliberately, not as a
  global catch-all.
- Lint is the stack's standard and belongs in the project; run what is installed, install nothing
  unasked.
- Pitfalls:
  - Never combine `v-if` and `v-for` on the same element.
  - Never mutate a prop directly — report a change to the parent through an event.
  - **Security:** a form using `@submit.prevent` also needs `method="post"` on the `<form>` element.
    The handler only exists once hydration finishes; a submit before that point (a password manager
    pressing enter, a slow connection, a blocked JS bundle) triggers the browser's native submit.
    Without `method` that is a GET to the current URL — a form carrying credentials puts the values
    in the address bar, browser history and server log. Applies to every server-rendered app, not
    only auth forms (see GHSA-gj2h-2fpw-fhv9, the same bug in `@nuxt/ui` before 4.8.1).

## `CR-vue-sfc-order` — Fixed SFC block order

summary: template, script setup, style

- Order SFC blocks as `<template>`, `<script setup>`, `<style>`.

## `CR-vue-state-store` — Store module for shared state

summary: Pinia store instead of provide/inject

- Keep state shared across the app in a dedicated store module (Pinia), not in `provide`/`inject`.

## `CR-vue-toolchain` — Lint and format tooling

summary: ESLint with eslint-plugin-vue plus Prettier by default, or what the project has set up

- ESLint with `eslint-plugin-vue` and Prettier for formatting are the template's usual choice; what
  the project actually has installed and configured governs (see `R-code-tools`).
