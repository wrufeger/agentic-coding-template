---
name: act-a11y
description: Use when asked to check accessibility, whether something is usable with keyboard or screen reader, or against WCAG, for one page or component. Gives a severity-ranked list of findings and fixes the ones you approve. Not for checking a build against its design - use act-design-build.
---

# Check accessibility

Checks an existing interface for use without a mouse, without color vision, and with a screen
reader. Differs from `act-design-build`, which checks against a **template** ("does it look
right?"): this checks **usability** ("can everyone operate it?") — a match to the template can
still be unusable.

1. **Scope it.** One page or component, never "the whole app", or the findings list never gets
   worked through.
2. **Measure automatically where possible**, e.g. an `axe-core` run via a browser-automation tool
   against the running page — catches missing labels, low contrast, duplicate IDs, missing
   language tags. Green there is not "accessible", only part of it.
3. **Check by hand what no tool sees**, heaviest first: keyboard (every control reachable with Tab,
   operable with Enter/Space, content order, no trap you can't tab out of); focus (visibly marked,
   moves into a dialog on open and back on close); structure (headings without skipped levels, a
   `div` with a click handler is not a button, form fields tied to their label); color (an
   error/success shown by color alone needs a second cue — text, icon, position); motion
   (switchable, respects `prefers-reduced-motion`).
4. **List findings by severity**, one line each — what, where (`path:line` or DOM selector), who
   it affects, a fix — ordered **blocks use** → **much harder** → **cosmetic**. Nothing changes
   before this list exists.
5. **Fix what's approved**, top to bottom, re-measuring after each group — a focus-order fix tends
   to shift something else.
6. Evidence (before/after run, fixed items), then `act-commit`.

## Limits

- No substitute for testing with real assistive-technology users — finds craftsmanship errors, not
  bad interaction design.
- No conformance claim ("meets WCAG AA"); only what was found and fixed is reported.
- No interface rebuild: a structural problem found here is a `docs/ai/work/backlog/` entry, not a
  side rebuild.
- `aria-*` only where native HTML doesn't reach — wrong ARIA is worse than none.
