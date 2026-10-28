# Coding rules — Nuxt

summary: directory conventions, data fetching, runtime config, SSR mode, tooling
requires: vue, typescript

Rules for Nuxt projects. Group IDs (`CR-nuxt-<name>`) are stable and never reassigned; a group
whose purpose no longer holds gets a new ID and is listed as `retired:` in this header.

On Nuxt 5 the set `nuxt5` (`.act/coding/nuxt5.md`) adds to this one. `init` checks it when
`package.json` names `nuxt` at major 5. If the set's line is missing from
`docs/project/coding_rules.md` on a Nuxt 5 project (one set up before the set existed), read
`.act/coding/nuxt5.md` before touching Nuxt code and suggest adding
`- [x] use: .act/coding/nuxt5.md` with its groups; an unchecked line is the owner's choice.

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

- Path aliases, by installed Nuxt major (`R-code-version`). Since Nuxt 4, `~` points at `app/`, so without its
  own entry `~/types` resolves somewhere other than `~types`.
  - Nuxt 4 and later: declare aliases only in `nuxt.config.ts` (`alias`); Nuxt copies each into the generated
    `.nuxt/tsconfig*.json`. The root `tsconfig.json` holds nothing but `references` to those generated configs
    and never its own `paths`: with `files: []` plus `references` a `paths` there replaces nothing, it simply
    does not reach the referenced projects, so the alias works nowhere. Only a root that extends a generated
    config replaces the whole generated mapping with its `paths`, and the framework aliases disappear.
  - Nuxt 3: declare aliases in `nuxt.config.ts` as well; a root `tsconfig.json` that extends
    `./.nuxt/tsconfig.json` may add `paths` only if it repeats every generated entry. Nuxt 3 also writes each
    `alias` into the generated `paths`, so the `nuxt.config.ts` entry alone is enough; the generated
    `.nuxt/tsconfig.json` shows it.
- Files the generated contexts leave out (unit and e2e tests, test-runner configs) are skipped by
  `nuxt typecheck` without a message. Add them through Nuxt's TypeScript options in `nuxt.config.ts`
  (`typescript.tsConfig.include`, or the per-context `typescript.sharedTsConfig` / `typescript.nodeTsConfig`
  / `typescript.tsConfig` objects on Nuxt 4; the server context via `nitro.typescript.tsConfig`), then prove each context once: put a deliberate type error in one
  file of it, see `nuxt typecheck` fail, remove it. Check the option names in the docs of the installed Nuxt
  version before using them.
- pnpm projects: see the package-manager notes in the JavaScript rules.
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
    port and HMR/WebSocket errors follow. If it is a server the assistant started itself, end exactly
    that process instead of configuring a custom HMR port. Find the listening PID with
    `(Get-NetTCPConnection -LocalPort <port> -State Listen).OwningProcess`, or with
    `netstat -ano | findstr /C:":<port> " | findstr LISTENING` — plain `findstr ":<port> "` also
    matches longer port numbers, and lines without `LISTENING` belong to clients — then
    `taskkill /PID <pid> /F`; elsewhere `lsof -iTCP:<port> -sTCP:LISTEN`, `kill <pid>`. A server on
    the owner's port is theirs: ask first (`R-safe-dev-server`).

## `CR-nuxt-root-folders` — Fixed root folders with their own aliases

summary: /types, /constants, /server and shared/utils/ at the repo root, each the only place of its kind

- Keep four folders at the repository root, each with its own alias and each the only place of its kind:
  `/types` (`~types`, shared types and interfaces), `/constants` (`~constants`, constants, enumerations,
  fixed keys), `/server` (`~server`, the Nitro backend), `shared/utils/` (Nuxt's `#shared`, code that the app
  and the server both run, such as formatting, validation or calculations).
- Import types and constants from there instead of duplicating them in components. A second type folder
  under `app/types/` or `shared/types/` is a mistake, not an addition: types stay in `/types`.
- Code in `shared/` imports no Vue and no Nitro code (Nuxt's own limit). Code only the app runs stays in
  `app/utils/`, code only the server runs in `server/utils/`.
- `shared/` needs Nuxt 3.14 or later (`R-code-version`). Nuxt 4 auto-imports `shared/utils/` in app and server;
  Nuxt 3 does so only with `future.compatibilityVersion: 4`, otherwise import from `#shared/utils/…`.

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
