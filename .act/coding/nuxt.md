# Coding rules — Nuxt

summary: directory conventions, data fetching, runtime config, SSR mode, tooling
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

## `CR-nuxt-ssr` — Choose the SSR mode on purpose

summary: ask before assuming SSR, know the hydration cost, check for mismatches after SSR work

- `ssr: false` or a plain SPA is often the simpler choice for a purely local UI with no SEO or
  first-paint requirement (e.g. an admin tool). Ask the user once, when scaffolding or restructuring
  the app, instead of defaulting to SSR without asking.
- Know what SSR costs: every page render runs twice, once on the server and once on the client.
  Anything that only exists in the browser or differs between the two runs — timestamps, random
  values, `window`, `localStorage`, locale or timezone detection — produces a hydration mismatch.
- After working on a component that renders server-side, check for hydration errors on purpose:
  load the page in the browser and read the console warning "Hydration ... mismatch" — it names the
  component and the node. Treat that warning as a finding, not a footnote.
- Known causes and their fix, in short: gate browser-only values behind `onMounted`/
  `import.meta.client`; share request-scoped state through `useState`, never a module-level `ref`;
  fix invalid HTML nesting (e.g. a block element inside a `<p>`); reach for `<ClientOnly>` only as
  the last resort.
- Copying a `useFetch`/`useAsyncData` result into your own `ref` is a common hydration-mismatch
  cause too — see `CR-nuxt-basics` for why and the fix, not repeated here.

## `CR-nuxt-toolchain` — Lint and format tooling

summary: ESLint with `@nuxt/eslint` plus Prettier, whichever the project has set up

- ESLint with `@nuxt/eslint`, configured in `eslint.config.mjs`, and Prettier for formatting are the
  template's usual choice; what the project actually has installed and configured governs
  (see `R-code-tools`).

## `CR-nuxt-tests` — Unit and end-to-end tests

summary: vitest/Playwright by default, but whichever suite the project runs must pass

- `vitest` (`vitest.config.ts`) for unit and component tests, `@playwright/test`
  (`playwright.config.ts`) for end-to-end tests — the template's usual choice; if the project has a
  different test runner installed and configured (e.g. Selenium, Nightwatch, Cypress), use that one
  instead (see `R-code-tools`).
- Whichever test suites the project actually has exist and run; a change that breaks them is not done.
