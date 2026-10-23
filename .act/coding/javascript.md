# Coding rules — JavaScript

summary: ESM, modern syntax, pinned Node version, ESLint flat config, Prettier, built-in or Vitest tests, handled promises

Rules for JavaScript on Node.js in projects without TypeScript; with TypeScript the `typescript` set
applies. Group IDs (`CR-javascript-<name>`) are stable and never reassigned; a group whose purpose no
longer holds gets a new ID and is listed as `retired:` in this header.

## `CR-javascript-basics` — Modern language defaults

summary: ESM, const/let, strict equality, async/await, explicit errors

- Use ES modules: `"type": "module"` in `package.json`, `import`/`export`, the `node:` prefix for
  built-ins (`import fs from "node:fs/promises"`), and the file extension in relative imports. No new
  CommonJS (`require`, `module.exports`); `__dirname` becomes `import.meta.dirname` (Node 20.11+).
- `const` by default, `let` where reassigned, never `var`.
- Compare with `===`/`!==`; `==` only for the deliberate `x == null` check, with a comment.
- `async`/`await` over `.then` chains. `forEach` does not wait for an async callback — use
  `for…of` with `await`, or `Promise.all` over `map` when the calls are independent.
- Throw `Error` objects (with `cause` when wrapping), never strings. Every error message states what
  failed and with what value.
- Use the standard library and built-ins (`fetch`, `structuredClone`, `node:test`, `util.parseArgs`)
  before adding a package.
- Describe the shape of structured data with a JSDoc `@typedef`, not as a loose object passed around.

## `CR-javascript-promises` — No floating promises

summary: every promise awaited, returned or caught; unhandled rejections end the process

- Every promise is awaited, returned, or ends in `.catch(...)`. A call to an async function as a bare
  statement hides its failure; on Node 15+ an unhandled rejection terminates the process.
- No `async` function as an event handler or `setInterval` callback without its own `try/catch`.
- No `new Promise(async (resolve) => …)`; no `await` in a loop where the calls are independent.
- ESLint core cannot find floating promises (`@typescript-eslint/no-floating-promises` needs types), so
  review for them, and set a top-level handler for `unhandledRejection` that logs and exits non-zero.

## `CR-javascript-toolchain` — Node version, lint, format, tests

summary: Node version pinned, ESLint 9+ flat config, Prettier, node:test or Vitest, lockfile

- Pin the Node.js version: `engines.node` in `package.json` plus `.nvmrc` (or `.node-version`), and use
  the same version in CI. Use an active LTS line; check the installed version (`R-code-version`).
- ESLint from v9 reads only the flat config `eslint.config.js`; `.eslintrc*` is legacy and not used
  unless the project still runs ESLint 8. Run what the project has configured (`R-code-tools`).
- Prettier is the template's usual formatter; ESLint covers correctness only, with
  `eslint-config-prettier` where both run — not a second style guide.
- Tests: the built-in `node:test` runner (`node --test`) or Vitest, whichever the project has set up.
- Commit the package manager's lockfile and install in CI from it, frozen: `npm ci`, `pnpm install
  --frozen-lockfile` or `yarn install --immutable`, never a plain install. With pnpm, `pnpm update` and
  `pnpm why <package>` replace `npm update` / `npm ls`; script arguments go without `--` (`pnpm run test -t name`).
- A failing lint or test is fixed in the code, not silenced with `eslint-disable` (`R-code-checks-intact`).
