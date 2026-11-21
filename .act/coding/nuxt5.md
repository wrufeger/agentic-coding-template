# Coding rules — Nuxt 5

summary: nightly channel, modules, Nitro 3/h3 v2, typed routing and `$fetch`, Unhead 3, checks after every update
requires: nuxt

Rules for projects on Nuxt 5, written against its nightly channel before the stable release. They add to
`CR-nuxt-*` and replace none of it. `init` checks this set when `package.json` names `nuxt` at major 5 (`^5.0.0`,
`npm:nuxt-nightly@5x`). Group IDs (`CR-nuxt5-<name>`) are stable and never reassigned; a group whose purpose no
longer holds gets a new ID and is listed as `retired:` in this header.

## `CR-nuxt5-channel` — Nightly channel and versions

summary: `nuxt-nightly@5x` as a tag, the lockfile as the only pin, pnpm re-resolving the tag, the nightly's `vue` range, majors in step with Nuxt, DevTools explicit, one package moved without Nuxt

- Until the stable release, list `nuxt` as `"npm:nuxt-nightly@5x"` — a tag, never a build number. If `npm install`
  (`pnpm install`) writes a fixed version, set it back to `@5x` by hand and install again (with pnpm that install is
  itself a Nuxt update, see below); only the lockfile pins the state. Drops once `nuxt/nuxt` tags `v5.0.0`
  (github.com/nuxt/nuxt/releases); then `^5.0.0`.
- Move forward with `npm update nuxt` (`pnpm update nuxt`), as a commit of its own, followed by the full check
  from `CR-nuxt5-checks`.
- Direct dependencies that Nuxt brings along stay on the same major as Nuxt does (e.g. `vue-router` 5,
  `@unhead/vue` 3); after every update, `npm ls <package>` (`pnpm why <package>`) shows one copy of each.
- Node 22.21 or 24.11 at least.
- Install `@nuxt/devtools` explicitly as a devDependency; run it only in the dev server and only with
  `NUXT_DEVTOOLS=1`, and confirm each browser once with the code from the dev terminal. Never set
  `devtools.disableAuthorization`.
- With pnpm and `nuxt` as an alias on the channel tag, every write of the lockfile can re-resolve the tag and move
  Nuxt to a newer nightly: `pnpm add`, `pnpm install` after a hand edit, `pnpm update <package> --depth Infinity` for
  a transitive fix; even with Nuxt pinned exactly in `package.json` its subtree was re-resolved. So with pnpm, add,
  remove or update packages only right after a deliberate Nuxt update (own commit, full check chain), then confirm
  with `pnpm why nuxt` that the resolved Nuxt is unchanged. Drops once Nuxt 5 ships a stable release and the project
  leaves the channel tag.
- To move a single package (a security fix) without moving Nuxt, with pnpm: set `nuxt` in `package.json` for the run to
  the exact version the lockfile holds, update the package, restore `package.json`, then set the lockfile's specifier
  for `nuxt` back to the channel tag. Afterwards `pnpm install --frozen-lockfile` must pass and the lockfile diff shows
  new entries only, none changed or removed; otherwise start over as a deliberate Nuxt update. A nightly CLI that moved
  along is taken back in the lockfile. The same steps lift the module copies named in `CR-nuxt5-checks` to the fixed
  version without moving the nightly. Drops with the pnpm line above.
- A nightly can raise its own `vue` range and peer ranges such as `vue-router`, also within a major; a project entry
  left on the old minimum keeps a second copy. After every move, read the nightly's ranges (`npm view
  <nightly>@<version> dependencies.vue peerDependencies`, `pnpm view` alike), raise your entries to them, then `npm
  ls vue` / `pnpm why vue` (and the same for `vue-router`) shows one version. Run `nuxt prepare` too: the
  generated ESLint config can point at the old store path until it runs (`postinstall` usually does it).
- pnpm 11's `minimumReleaseAge` makes `pnpm update nuxt` take the newest nightly older than that age: do not work
  around it; name the version actually installed in the commit and the upgrade log.
- pnpm measures `minimumReleaseAge` from the moment a version appeared on npm, and that moment may come after its
  GitHub release; a version that looks old enough by the release date can still be held back.
- After `dev` or `build`, read the diff of `package.json`: every entry the tooling added on its own is one you can
  explain.

## `CR-nuxt5-modules` — Modules under Nuxt 5

summary: `NUXT_B8013` means switched off, Pinia 4 with its peer, the i18n way back, bundled icons, the Nitro v2 bridge only in modules

- `NUXT_B8013` switches off a module whose `compatibility` field does not match, with nothing but a warning: check
  the field before the update, read the warnings after it.
- Pinia 4: `@pinia/nuxt` 1 or later, `@vue/devtools-api` ^8 as a direct dependency.
- `@nuxtjs/i18n` 10.6, before it supports Nuxt 5: `i18n.experimental.nitroContextDetection: false`. Without it a
  path without locale prefix gets no server redirect (checked with strategy `prefix` on nightly
  `5.0.0-2611122105`); as reported, the default waits for the Nitro hook `render:before`, which Nitro 3 never calls,
  and the client redirect ends in a hydration mismatch. Drop it once a release closes
  nuxt-modules/i18n#4066 (Nuxt 5 and Nitro 3 support). `experimental.nitroViteEnvironment: false` is no longer
  needed from nightly `5.0.0-2611031025` on; remove it once `build` and the E2E tests pass without it.
- Use the bundled icon setup from `CR-nuxt-ssr` and an E2E check that icons render and no request goes to the public
  Iconify API. Older `@nuxt/icon` versions needed a workaround: a server-side icon provider plus a hand-set cache
  `allowQuery` for the icon endpoint. It is no longer needed from `@nuxt/icon` 2.6.3 on (reported on Nitro 3); look
  for both in the config and remove them.
- Never rebuild the Nitro v2 bridge (`NUXT_B9003`) in your own code.

## `CR-nuxt5-server` — Nitro 3 and h3 v2

summary: explicit imports from `nuxt/server`, `event.req` as a web request, typed bodies, `status`/`statusText`, no comma in export-line comments, headers and CSP (nonce in dev, keep-alive hang), no file deleted under the owner's dev server

- In `server/`, import `defineEventHandler`, `readBody`, `getQuery`, `createError` … from `nuxt/server`, and define
  plugins with `definePlugin` from `nitro`; `server/utils/` stays auto-imported.
- `event.req` is the web `Request` (there is no `event.node`); read a multipart body with `event.req.formData()`.
- `readBody<T>()` with an `interface` of its own, fallback `.catch((): Body => ({}))`. The type is no validation —
  validate the body as before (e.g. with a schema library).
- Type a response at the return value (`const response: ApiThing = …; return response`), the type in `/types`
  (`CR-nuxt-root-folders`).
- Errors with `createError({ status, statusText })`; `statusText` in ASCII only (e.g. `'Unprocessable Entity'`),
  localized text goes into `data`.
- On the client, `createError({ data })` arrives under `response._data.data`; the field errors of a 422 sit under
  `…data.errors` (e.g. for Nuxt UI's `UForm.setErrors`).
- `useRuntimeConfig()` without `event`.
- In a folder auto-imported into the server (`server/utils/`, `shared/utils/` …) no comma in a line comment after an
  exported declaration: the export scan (`mlly`) reads the word after the comma as one more export and writes it
  into `.nuxt/types/server-imports.mjs`, and the server build fails with `MISSING_EXPORT` once a module keeps that
  file from being tree-shaken (seen with `mlly` 1.8.2, `@nuxtjs/i18n` 10.6.0, nightly `5.0.0-2611122105`). Put the
  comment above the line. Drops once the generated file lists only real exports (no upstream report known).
- Fixed security headers (not the CSP) go into a route rule `/**` in `nuxt.config`: Nitro 3 serves files from
  `public/` and `/_nuxt/` before the app's middlewares, so a header a middleware sets never reaches them. Check
  the headers against the production build.
- Reported by a project, not reproduced: Nuxt 5 sets no CSP itself and no CSP module supports it yet. Set the CSP
  header in a server plugin on `render:html` (`useServerHooks` from `nuxt/server`), with hashes for the fixed inline
  scripts and a nonce per request on the payload script; Nuxt puts a nonce on its own streaming scripts only if a
  head script already carries one. A CSP an early middleware sets overrides the renderer's, so set one there only
  for API routes. Drops once a CSP module (e.g. `nuxt-security`) declares Nuxt 5 support.
- Strict nonce CSP in dev: the dev error badge (reported from nightly 2611132210) reads a nonce only from head tags
  present before `render:html` runs, so a nonce that first appears inside `render:html` leaves the badge blocked. In
  dev only (`import.meta.dev`) give the badge the nonce the payload script has, never `unsafe-inline`. Nitro's reload
  script on 5xx pages in dev (reported on Nitro 3.0.261103-rc) has no nonce at all; expect one CSP message from it
  and filter it out of console checks. The older workaround for the overlay is no longer needed from that nightly
  on; remove it. An E2E helper provokes the error with a 5xx response. This dev part drops once a nightly gives the
  dev badge the nonce set in `render:html` and gives the dev reload script on 5xx pages a nonce of its own.
- Keep-alive hang (reported with Nitro 3.0.261103-rc, srvx 1.0.8, h3 2.0.8, on Linux, Windows and the production
  build, nightly 2611172312): a request rejected early (413, 401) with its body unread leaves the next request on the
  same connection hanging until `keepAliveTimeout`. As a stopgap a server middleware sets `Connection: close` on
  unsafe methods, also in the headers of the error response. Drops once a release fixes the hang after an early
  rejection with an unread body; note that upstream issue by description next to the workaround.
- Keep-alive in dev: `Connection: close` stays, and in addition read the request body to its end before the early
  rejection. Only for unsafe methods, only with a known length up to the largest upload limit, never a body that is
  already read or locked, and around the whole middleware chain (`next()` in a try/catch), not only your own guard.
  Unit tests pass their own stub for `next`.
- Test the keep-alive hang with a POST over the limit followed by a second request through the same agent, and with
  several raw `node:http` clients in parallel sending a body just above the limit.
- After renaming or removing an export in `server/utils/`, restart your own test server (its port as
  `R-safe-dev-server` says) before tests against it count; the owner's server only after asking. No transitional alias for the old name. Never set `NUXT_IGNORE_LOCK` or `NUXT_LOCK=0`.
- Deleting a file from an auto-imported folder while the owner's dev server runs makes every page answer 500 until
  a restart: the running module graph keeps the old import. As the assistant never restarts that server, empty the
  file and leave it, delete it after the owner's next restart, or ask first. A test server started fresh per run is
  not affected.
- Every runtime dependency goes into `package.json`, even one that is already there transitively.

## `CR-nuxt5-app` — Pages, routing, data fetching, head

summary: `import.meta.*`, `query` instead of `params`, typed `$fetch` and route targets, server `navigateTo` and the query, Unhead 3 and its og hint, no `baseUrl`

- `import.meta.*` instead of `process.*` (`import.meta.client`, `import.meta.dev` …).
- `query` instead of `params` in the options of `$fetch`/`useFetch`.
- `$fetch` is typed from the generated server routes: a wrapper that takes free paths gets a narrow signature of its
  own (`type FreeFetch = <R>(request: string, options: FetchOptions) => Promise<R>`) and converts `$fetch` with
  `as unknown as FreeFetch`, with a comment saying why.
- With typed pages and `@nuxtjs/i18n`, a page target is a route name without the locale suffix:
  `localePath({ name, params, query })` or `<NuxtLinkLocale :to="{ name: … }">` — for `navigateTo`, `router.push`,
  `NuxtLink` and a Nuxt UI `to` as well; a plain path gets no locale prefix and ends in a 404. For the same reason,
  build `definePageMeta({ redirect })` relative to the current path.
- Unhead 3: no `hid`/`vmid`, deduplicate with `key`; a dev hint about `og:*` or the description is a finding,
  except the known case below.
- Unhead 3 reports `og-missing-title` on a page that carries other `og:` meta tags (often set app-wide) but no
  `og:title` (checked in Unhead 3.4.3, the validate plugin in `dist/plugins.mjs`). On a page that deliberately has
  no `og:title` (private page, error page), leave out the other `og:` tags there too; where that is not possible,
  treat the hint as a known false positive and re-check it after each Unhead update. Setting
  `rules: { 'og-missing-title': 'off' }` on the validate plugin silences it for every page, so it hides real cases.
- Every page sets its title, a public page its description too; the fallbacks (title template, `og:site_name`,
  default description) go into `app.vue` **and** `error.vue`, since Nuxt renders `error.vue` in place of `app.vue`.
  A head value that is missing is left out, never passed as `undefined` — `useSeoMeta({ description: undefined })`
  removes the fallback (so the `og:title` case above is solved by leaving tags out, not by `undefined`).
- A server-side `navigateTo` in middleware rebuilds `Location` from the router path, so the query comes out in the
  router's encoding (reported from nightly 2611151847): signed parameters, OAuth return links and shared links break
  without any error. On the server pass a relative target of the same origin with the option `external: true` (with
  `@nuxtjs/i18n` build that target with `localePath(...)`, else it loses the locale prefix); on the client leave
  navigation to the router. A test compares the exact search string in the `Location` header.
- Pin `workspaceDir` as the security line in `CR-nuxt-basics` says; it holds for Nuxt 5 as well.
- No `compilerOptions.baseUrl` in `tsconfig.json` — Nuxt ignores it; aliases go into `nuxt.config.ts` only
  (`CR-nuxt-basics`).

## `CR-nuxt5-checks` — Checks after every Nuxt update

summary: the full check chain, the type error list compared rather than counted, warnings (a list per nightly, a known listener warning), copies (how to count, the expected `@nuxt/schema` hit) and `invalid` in the tree, workarounds against upstream, a build before commits to auto-imported folders or `nuxt.config`, the typecheck in the own `buildDir`, a record

- Save the typecheck output before the update and compare the errors afterwards — the list, not the count.
- Then `npm run lint`, `typecheck`, `test`, `build`, `dev` (main pages answer 200, no hydration warning), the main
  pages once more against the built server with the browser console read (a module can break there only), and
  `test:e2e`; `dev` and the built server as your own test servers (port as `R-safe-dev-server` says), stopped
  afterwards.
- Also between updates, a commit that changes an auto-imported folder (`server/`, `shared/`, `app/composables/`,
  `app/utils/`) or `nuxt.config` runs `build` besides lint, typecheck and tests: they stay green on a broken export
  scan (`CR-nuxt5-server`), only the build fails. Build with its own `buildDir` and Nitro output dir as
  `CR-nuxt-tests` says, never into the owner's `.nuxt/` while their dev server runs (`R-safe-dev-server`).
- Keep the list of warnings per nightly and compare it after each update, as with the type errors. Reported with nightly
  2611151847 and `@nuxtjs/i18n` 10.6.0: new warnings `NUXT_B2003`, `NUXT_B2010`, `NUXT_B2014` and `NUXT_E8013`
  without any runtime effect; a new warning is looked up before it is accepted.
- Read the warnings (`NUXT_B8013`, `NUXT_B9003`, `[unhead]`), check for duplicate copies, run
  `python .act/scripts/security_scan.py --deps`.
- Count copies of a package with `npm ls <package>` / `pnpm why <package>`; folders under `node_modules/.pnpm` left from
  earlier installs stay until pnpm prunes them (`modulesCacheMaxAge`) and are not copies.
- Under the nightly, common modules still pull `@nuxt/kit` 4.x and with it an `@nuxt/schema` 4.x: the dependency scan
  reports the `workspaceDir` advisory (`CR-nuxt-basics`) on that copy, not on the nightly, so the hit is expected. Lift
  the copy as `CR-nuxt5-channel` describes for a single package. Drops once the common modules depend on a Nuxt 5 kit.
- A `MaxListenersExceededWarning` about `close` listeners on the server response in the nightly's `nuxt dev` is
  toolchain noise: the listeners come from the CLI, Vite, the server layer and stream helpers (with a TTY also the CLI's
  interface), their number depends on the kind of request, not on uptime, and falls back to none once the response
  closes; application code does not reach the response. Plain CLI output without the interface avoids it. Investigate
  only if it also shows in the production build or grows with a stream's lifetime. Drops once the warning no longer
  appears in `nuxt dev` on a current nightly.
- `npm ls --all 2>&1 | grep invalid`: fix a stale resolution with `npm update <package>` (with pnpm: `pnpm why
  <package>`, `pnpm update <package>`, under the pnpm line of `CR-nuxt5-channel`); entries already known stand
  in the upgrade log, report only new ones.
- Check every workaround in this set against the upstream issue or release it names; drop the one whose condition is
  met, and note it in the upgrade log. A workaround's exit condition (keep-alive, CSP) describes the upstream issue
  in words, so that a fix is noticed.
- `nuxt typecheck` takes the own `buildDir` variable like the build and the test servers (`CR-nuxt-tests`); a builder
  assignment that includes the typecheck names it, so the owner's `.nuxt/` stays untouched.
- Record every break in an upgrade log of the project (e.g. `docs/project/nuxt-5-upgrade.md`): the symptom quoted in
  short, the cause checked or marked **assumption**, the fix, the location. A general lesson becomes an own rule in
  `docs/project/coding_rules.md` and goes to the template through `act-feedback`.
