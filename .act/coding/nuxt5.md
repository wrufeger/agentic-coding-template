# Coding rules — Nuxt 5

summary: nightly channel, modules, Nitro 3/h3 v2, typed routing and `$fetch`, Unhead 3, checks after every update
requires: nuxt

Rules for projects on Nuxt 5, written against its nightly channel before the stable release. They add to
`CR-nuxt-*` and replace none of it. `init` checks this set when `package.json` names `nuxt` at major 5 (`^5.0.0`,
`npm:nuxt-nightly@5x`). Group IDs (`CR-nuxt5-<name>`) are stable and never reassigned; a group whose purpose no
longer holds gets a new ID and is listed as `retired:` in this header.

## `CR-nuxt5-channel` — Nightly channel and versions

summary: `nuxt-nightly@5x` as a tag, the lockfile as the only pin, majors in step with Nuxt, DevTools explicit

- Until the stable release, list `nuxt` as `"npm:nuxt-nightly@5x"` — a tag, never a build number. If `npm install`
  writes a fixed version, set it back to `@5x` by hand and install again; only the lockfile pins the state.
- Move forward with `npm update nuxt`, as a commit of its own, followed by the full check from `CR-nuxt5-checks`.
- Direct dependencies that Nuxt brings along stay on the same major as Nuxt does (e.g. `vue-router` 5,
  `@unhead/vue` 3); after every update, `npm ls <package>` shows one copy of each.
- Node 22.21 or 24.11 at least.
- Install `@nuxt/devtools` explicitly as a devDependency; run it only in the dev server and only with
  `NUXT_DEVTOOLS=1`, and confirm each browser once with the code from the dev terminal. Never set
  `devtools.disableAuthorization`.
- After `dev` or `build`, read the diff of `package.json`: every entry the tooling added on its own is one you can
  explain.

## `CR-nuxt5-modules` — Modules under Nuxt 5

summary: `NUXT_B8013` means switched off, Pinia 4 with its peer, the i18n way back, the Nitro v2 bridge only in modules

- `NUXT_B8013` switches off a module whose `compatibility` field does not match, with nothing but a warning: check
  the field before the update, read the warnings after it.
- Pinia 4: `@pinia/nuxt` 1 or later, `@vue/devtools-api` ^8 as a direct dependency.
- `@nuxtjs/i18n` 10.6, before it supports Nuxt 5: `experimental.nitroViteEnvironment: false` and
  `i18n.experimental.nitroContextDetection: false`; drop both once it does.
- Never rebuild the Nitro v2 bridge (`NUXT_B9003`) in your own code.

## `CR-nuxt5-server` — Nitro 3 and h3 v2

summary: explicit imports from `nuxt/server`, `event.req` as a web request, typed bodies, `status`/`statusText`

- In `server/`, import `defineEventHandler`, `readBody`, `getQuery`, `createError` … from `nuxt/server`, and define
  plugins with `definePlugin` from `nitro`; `server/utils/` stays auto-imported.
- `event.req` is the web `Request` (there is no `event.node`); read a multipart body with `event.req.formData()`.
- `readBody<T>()` with an `interface` of its own, fallback `.catch((): Body => ({}))`. The type is no validation —
  validate the body as before (e.g. with a schema library).
- Type a response at the return value (`const response: ApiThing = …; return response`), the type in the shared
  types folder (`CR-nuxt-root-folders`).
- Errors with `createError({ status, statusText })`; `statusText` in ASCII only (e.g. `'Unprocessable Entity'`),
  localized text goes into `data`.
- On the client, `createError({ data })` arrives under `response._data.data`; the field errors of a 422 sit under
  `…data.errors` (e.g. for Nuxt UI's `UForm.setErrors`).
- `useRuntimeConfig()` without `event`.
- After renaming or removing an export in `server/utils/`, restart your own test server (its port as
  `R-safe-dev-server` says) before tests against it count; the owner's server only after asking. No transitional alias for the old name. Never set `NUXT_IGNORE_LOCK` or `NUXT_LOCK=0`.
- Every runtime dependency goes into `package.json`, even one that is already there transitively.

## `CR-nuxt5-app` — Pages, routing, data fetching, head

summary: `import.meta.*`, `query` instead of `params`, typed `$fetch` and route targets, Unhead 3, no `baseUrl`

- `import.meta.*` instead of `process.*` (`import.meta.client`, `import.meta.dev` …).
- `query` instead of `params` in the options of `$fetch`/`useFetch`.
- `$fetch` is typed from the generated server routes: a wrapper that takes free paths gets a narrow signature of its
  own (`type FreeFetch = <R>(request: string, options: FetchOptions) => Promise<R>`) and converts `$fetch` with
  `as unknown as FreeFetch`, with a comment saying why.
- With typed pages and `@nuxtjs/i18n`, a page target is a route name without the locale suffix:
  `localePath({ name, params, query })` or `<NuxtLinkLocale :to="{ name: … }">` — for `navigateTo`, `router.push`,
  `NuxtLink` and a Nuxt UI `to` as well; a plain path gets no locale prefix and ends in a 404. For the same reason,
  build `definePageMeta({ redirect })` relative to the current path.
- Unhead 3: no `hid`/`vmid`, deduplicate with `key`; a dev hint about `og:*` or the description is a finding.
- Every page sets its title, a public page its description too; the fallbacks (title template, `og:site_name`,
  default description) go into `app.vue` **and** `error.vue`, since Nuxt renders `error.vue` in place of `app.vue`.
  A head value that is missing is left out, never passed as `undefined` — `useSeoMeta({ description: undefined })`
  removes the fallback.
- No `compilerOptions.baseUrl` in `tsconfig.json` — Nuxt ignores it; aliases go into `nuxt.config.ts` only
  (`CR-nuxt-basics`).

## `CR-nuxt5-checks` — Checks after every Nuxt update

summary: the full check chain, the type error list compared rather than counted, warnings, copies and `invalid` in the tree, a record

- Save the typecheck output before the update and compare the errors afterwards — the list, not the count.
- Then `npm run lint`, `typecheck`, `test`, `build`, `dev` (main pages answer 200, no hydration warning) and
  `test:e2e`; `dev` as your own test server (port as `R-safe-dev-server` says), stopped afterwards.
- Read the warnings (`NUXT_B8013`, `NUXT_B9003`, `[unhead]`), check for duplicate copies, run
  `python .act/scripts/security_scan.py --deps`.
- `npm ls --all 2>&1 | grep invalid`: fix a stale resolution with `npm update <package>`; entries already known stand
  in the upgrade log, report only new ones.
- Record every break in an upgrade log of the project (e.g. `docs/project/nuxt-5-upgrade.md`): the symptom quoted in
  short, the cause checked or marked **assumption**, the fix, the location. A general lesson becomes an own rule in
  `docs/project/coding_rules.md` and goes to the template through `act-feedback`.
