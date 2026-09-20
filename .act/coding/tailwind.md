# Coding rules — Tailwind

summary: utility-first styling, design tokens, dark mode, class sorting

Rules for Tailwind CSS, usually applied inside a frontend framework. Group IDs (`CR-tailwind-<name>`) are
stable and never reassigned; a group whose purpose no longer holds gets a new ID and is listed as `retired:`
in this header.

## `CR-tailwind-basics` — Established Tailwind defaults

summary: utilities in markup, tokens, theme, dark mode, extraction, tooling, pitfalls

- Write utility classes directly in markup; no separate CSS files without a concrete reason.
- Use design tokens (the spacing, color and radius scale from the config) instead of arbitrary values —
  `p-[13px]` only as a documented exception.
- Keep theme changes (colors, fonts, breakpoints) centralized in the Tailwind config, not scattered across
  files.
- Map dark mode through the configured tokens/variants, never parallel hardcoded color values.
- Extract a repeated class combination into a component/partial; never copy it around as a text snippet.
- Lint/format tooling is the stack's standard and belongs in the project: `prettier-plugin-tailwindcss` for
  automatic class sorting (layout, box model, typography, color, state), enforced by the formatter instead
  of sorted by hand. Run what is installed, install nothing unasked.
- Pitfalls:
  - Use `@apply` only in exceptions (e.g. base styles of a third-party component), never as the default way
    to style.
  - Keep `content` paths in the config correct — a wrong or missing path either drops classes that are
    actually used or leaves unused utility classes in the build.
