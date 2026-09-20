# Coding rules — Nuxt

summary: directory conventions, data fetching, runtime config, tooling
requires: vue, typescript

Rules for Nuxt projects. Group IDs (`CR-nuxt-<name>`) are stable and never reassigned; a group
whose purpose no longer holds gets a new ID and is listed as `retired:` in this header.

## `CR-nuxt-basics` — Established Nuxt defaults

summary: directory layout, data fetching, typed handlers, runtime config, pitfalls

- Follow the directory convention (`pages/`, `components/`, `composables/`, `server/`) instead of
  inventing a structure; use auto-imports, no manual re-exports for files in those directories.
- Read data with `useFetch`/`useAsyncData` while rendering, use `$fetch` for one-off writes and actions.
- Never copy the return value of `useFetch`/`useAsyncData` into your own `ref` — pass the returned
  object through and `await` it where `data`/`status`/`error` reach the template. Copying loses
  awaitability: the call resolves later, the server renders without data, the client fills it in, and
  the result is a hydration mismatch.

      ```ts
      // Wrong — awaitability is lost
      function useThing() {
        const result = ref()
        useFetch('/api/thing').then(r => (result.value = r.data.value))
        return result
      }

      // Right — pass the returned object through unchanged
      async function useThing() {
        return await useFetch('/api/thing')
      }
      ```

- Declare path aliases in `tsconfig.json` **and** `nuxt.config.ts`. Since Nuxt 4, `~` points at `app/`,
  so without its own entry `~/types` resolves somewhere other than `~types`.
- Use `runtimeConfig` for configuration values instead of reading `process.env` in components; secrets
  live in the private part of `runtimeConfig`, never under `public`.
- Write out types for props, emits, store actions, composables and `defineEventHandler`, including
  return types.
- Name server routes under `server/api/` with a verb suffix (`login.post.ts`, `users.get.ts`) and return
  failures with `createError` and a matching HTTP status — never swallow an error or answer 200.
- Lint and typecheck are the stack's standard and belong in the project; `nuxt typecheck` needs `vue-tsc`
  as a dependency, without it there is no typecheck. Run what is installed, install nothing unasked.
- Keep the npm scripts named the same everywhere: `lint` (`eslint .`), `typecheck` (`nuxt typecheck`),
  plus `test` (`vitest run`) and `test:e2e` (`playwright test`) where tests exist.
- Pitfalls:
  - SSR code must not touch browser globals (`window`, `document`) without a guard.
  - Use `<ClientOnly>` only where a component genuinely cannot render on the server, not as a default fix.
  - **Security:** never keep per-request state in a module-level `ref`/`reactive`. On the server such a
    value outlives the request and is shared between users — the next request sees the previous one's
    data. Use `useState` for state that must survive the request.
  - Forms with `@submit.prevent` also need `method="post"` (see `CR-vue-basics`).
  - **Windows:** an aborted dev server can keep its port bound; the next start moves to the next free
    port and HMR/WebSocket errors follow. Kill the running process (`netstat -ano | findstr :3000`,
    `taskkill /PID <pid> /F`; `lsof -i :3000`, `kill <pid>`) instead of configuring a custom HMR port.

## `CR-nuxt-root-folders` — Fixed root folders with their own aliases

summary: /types, /constants and /server at the repo root, each the only place of its kind

- Keep three folders at the repository root, each with its own alias and each the only place of its kind:
  `/types` (`~types`, shared types and interfaces), `/constants` (`~constants`, constants, enumerations,
  fixed keys), `/server` (`~server`, the Nitro backend).
- Import types and constants from there instead of duplicating them in components. A second type folder
  under `app/types/` is a mistake, not an addition.

## `CR-nuxt-toolchain` — Lint and format tooling

summary: ESLint with @nuxt/eslint plus Prettier

- ESLint with `@nuxt/eslint`, configured in `eslint.config.mjs`.
- Prettier for formatting.

## `CR-nuxt-tests` — Unit and end-to-end tests

summary: vitest for unit tests, Playwright for end-to-end tests

- Unit and component tests with `vitest` (`vitest.config.ts`).
- End-to-end tests with `@playwright/test` (`playwright.config.ts`).
- Both test suites exist and run; a change that breaks them is not done.
