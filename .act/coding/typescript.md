# Coding rules — TypeScript

summary: strict mode, no any, typed errors, module structure, tooling

Rules for TypeScript projects in strict mode. Group IDs (`CR-typescript-<name>`) are stable and never
reassigned; a group whose purpose no longer holds gets a new ID and is listed as `retired:` in this
header.

## `CR-typescript-basics` — Strict mode, narrowing, typed errors

summary: strict, no any, return types, as/!, error handling, lint

- Enable `strict: true` in `tsconfig.json`; loosen it only with a comment explaining why.
- Never use `any` — type unknown values as `unknown` and narrow them before use.
- Draw the line where strictness stops helping: a type nested deeper than the code it describes
  (heavily nested generics, chained conditional types, stretched mapped types) is worse than a
  simpler one. Fall back to `unknown` with a check at the boundary, or a narrow `interface` for just
  the fields used, with a comment saying why — the exception serves readability, not convenience,
  and `any` stays excluded even here.
- Give exported functions an explicit return type instead of relying on inference.
- Use `as Type` only when narrowing cannot do the job, and say why in a comment.
- Never use the non-null assertion (`!`) — it suppresses a real nullability check.
- Raise errors as typed Error objects, never `throw` an arbitrary value; whatever is thrown, logged
  or rethrown, its message names what failed and with what — a caller must find the cause without
  opening the source.
- Lint and typecheck (`tsc --noEmit`) are the stack's standard and belong in the project; run what is
  installed, install nothing unasked.

## `CR-typescript-conventions` — interface, type, generics

summary: interface for shapes, type for unions, no enums, generics from second use

- Use `interface` for object shapes/contracts, `type` for unions, intersections and derived types.
- Avoid enums — use `as const` objects or union literal types instead.
- Introduce a generic only once a second concrete use exists; a concrete type is fine for the first.

## `CR-typescript-module-structure` — Central types, explicit exports

summary: shared types in one place, public exports through an index

- Define shared types/schemas in one central place and import them, instead of redeclaring them per
  module.
- Expose a module's public API through an explicit index, not deep import paths into another module.

## `CR-typescript-toolchain` — Lint and format tooling

summary: ESLint with `@typescript-eslint` plus Prettier by default, or what the project has set up

- ESLint with `@typescript-eslint` and Prettier for formatting are the template's usual choice; what
  the project actually has installed and configured governs (see `R-code-tools`).
