# Coding rules — React

summary: rules of hooks, keys, effects for synchronization only, React 19 changes, server components, Testing Library

Rules for React. They apply together with `javascript` or `typescript` — tick one of the two as well; the
template cannot express "one of both" as a requirement. Version-dependent items name the version they
need; check the installed React version first (`R-code-version`). Group IDs (`CR-react-<name>`) are stable
and never reassigned; a group whose purpose no longer holds gets a new ID and is listed as `retired:` in
this header.

## `CR-react-components` — Components, hooks and keys

summary: rules of hooks, pure render, stable keys, no state copied from props

- Call hooks only at the top level of a component or custom hook, never in a condition, loop or nested
  function; the `eslint-plugin-react-hooks` rules stay on and are not silenced.
- Keep render pure: no mutation of props or state, no fetch, timer or `Date.now()` in the render body.
- `key` is a stable id from the data, never the array index for a list that can reorder, insert or delete,
  and never `Math.random()`.
- Do not copy a prop into state to "initialize" it; use the prop, or lift the state.
- Define components at module level, never inside another component: a nested definition remounts its
  subtree on every render.
- Memoize (`useMemo`, `useCallback`, `memo`) for a measured problem only; with the React Compiler enabled
  in the project, leave existing hand-written memoization alone (the compiler's docs advise this) and add
  none; remove it only after careful testing.

## `CR-react-effects` — Effects only to synchronize with the outside

summary: no derived state in effects, complete dependencies, cleanup, data loading by the project's choice

- An effect synchronizes with something outside React (network, subscription, DOM API, timer). Anything
  computable from props and state is computed during render; an event's consequence belongs in the handler.
- A `useEffect` that only calls `setState` from other state is a bug in the making: derive the value, or
  reset by changing the component's `key`.
- Declare every reactive value the effect reads as a dependency; fix a wrong list by restructuring, never
  by removing the dependency or disabling the lint rule.
- Return a cleanup for every subscription, timer and request (`AbortController`); effects run twice on
  mount in development under `StrictMode`, and the code must survive that.
- Use the data-loading approach the project already has (TanStack Query, SWR, framework loaders); no
  hand-rolled `fetch` in an effect where one exists.

## `CR-react-19` — Changes in React 19 and later

summary: ref as prop, use, Actions, context provider, removed APIs

- From React 19, a function component takes `ref` as a normal prop; `forwardRef` is not needed in new code.
  On React 18 and earlier, `forwardRef` stays.
- `use(promise)` and `use(context)` read a promise or context during render and, unlike other hooks, may
  be called in a condition. The promise comes from a cache or a parent, not from the same render.
- Form handling: a function as `<form action>`, `useActionState` (formerly `useFormState`),
  `useFormStatus` (from `react-dom`) and `useOptimistic` replace hand-written pending and error state.
- Removed in 19, do not write them: `propTypes` and `defaultProps` on function components, `ReactDOM.render`
  and `hydrate` (use `createRoot`/`hydrateRoot`), string refs, legacy context.
- `useEffectEvent` exists from React 19.2; before that, keep the latest value in a ref.

## `CR-react-structure` — Server components and testing

summary: server components only with a supporting framework, "use client" boundary, Testing Library by role

- Server Components, `"use server"` and `"use client"` need a framework or bundler that supports them
  (Next.js App Router; React Router's support is still experimental). In a plain Vite single-page app they do not exist; do
  not add the directives there.
- With Server Components, a component is a server component by default: no state, effects or browser APIs.
  Put `"use client"` on the smallest leaf that needs interactivity; props across the boundary must be
  serializable.
- Test with `@testing-library/react` and `user-event`: find elements by role, label or text as a user
  would, not by class name or internals; prefer `findBy…` over fixed waits.
- Run tests with the runner the project has set up (Vitest or Jest), and mock the network at its boundary
  (`msw`), not the component's own modules.
