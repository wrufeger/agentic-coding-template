# Coding rules — CSS

summary: custom-property tokens, low specificity, no !important, mobile-first, stylelint

Rules for hand-written CSS (and SCSS) in projects that do not use Tailwind. Do not tick this set in a
project that ticks `tailwind`: utility classes and a hand-written cascade pull in opposite directions, and
the rules below would contradict the Tailwind ones (`@apply`, separate CSS files). Group IDs
(`CR-css-<name>`) are stable and never reassigned; a group whose purpose no longer holds gets a new ID and
is listed as `retired:` in this header.

## `CR-css-tokens` — Design tokens as custom properties

summary: one place for colors, spacing and type; no repeated literals; dark mode by remapping

- Define colors, spacing, radii, font sizes and z-index layers once as custom properties on `:root`
  (`--color-surface`, `--space-2`) and use `var(--…)` everywhere else; a hex value or `13px` repeated in
  rule bodies is a missing token.
- Name tokens by role (`--color-text-muted`), not by value (`--grey-600`) or place (`--header-blue`).
- Dark mode and themes remap the same tokens under a selector or `prefers-color-scheme`; never a second
  set of hardcoded colors in parallel rules.
- Give `var()` a fallback only where the property can be absent on purpose, not to hide a typo in a name.

## `CR-css-cascade` — Specificity and the cascade

summary: flat selectors, no !important, no id selectors, layers for ordering, one naming scheme

- Keep selectors flat: a class, at most one more level (`.card__title`, `.nav a`). No `#id` selectors, no
  chains of three or more, no element-qualified classes (`div.card`).
- No `!important`. If a rule does not win, lower the specificity of the competing rule or order the sources
  with `@layer` (supported in all current browsers since 2022); an exception for a utility that must win
  is documented at the declaration.
- Pick one naming scheme (BEM or what the project already uses) and keep it; do not mix schemes in one
  file.
- Style by class, never by DOM structure that a markup change would break (`div > div:nth-child(3)`).
- Do not set `outline: none` without a visible `:focus-visible` replacement.

## `CR-css-layout` — Layout and responsiveness

summary: mobile-first min-width queries, flex/grid, relative units, logical properties

- Write the base rules for the smallest screen and add `@media (min-width: …)` for larger ones; breakpoints
  come from tokens or one list, not from numbers invented per component.
- Use flexbox and grid for layout, `gap` for spacing between items; no floats or fixed heights that clip
  text.
- Size text and spacing in `rem`/`em`, not `px`, so user font settings still work; `px` is fine for
  borders and hairlines.
- Prefer logical properties (`margin-inline`, `padding-block`) in new code when the project supports
  right-to-left text.
- Check browser-support claims against the project's `browserslist` or stated targets before using a new
  feature (container queries, `:has()`, nesting); do not assume the newest syntax is available.

## `CR-css-toolchain` — Lint and format tooling

summary: stylelint by default, formatter of the project, SCSS only if the project already uses it

- `stylelint` with the project's shared config is the template's usual choice for linting, `prettier` for
  formatting — either way, run what the project actually has configured (see `R-code-tools`).
- Do not introduce SCSS, PostCSS plugins or a CSS-in-JS library into a project that has none; with native
  nesting and custom properties most of the old reasons are gone.
- In SCSS, keep nesting to three levels at most and use `@use` / `@forward`, not `@import`, which is deprecated since Dart Sass 1.80.
