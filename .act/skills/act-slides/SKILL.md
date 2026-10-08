---
name: act-slides
description: Use when asked for a presentation, slides about the project, a talk, or a training deck. Produces the slides as versioned Markdown built from the existing docs and exports them to HTML or PDF.
---

# Presentation about the project

Produces a slide deck about this project — training, handover, talk, or status meeting. **The
slides are source text**: a Markdown file in the repo, versioned, diffable, no binary format in
git. Content comes from the repo, not imagination: whatever a slide claims must be backed by
`README.md`, `docs/project/`, or the project's open work (`docs/ai/work/`) — a deck that diverges
from the project is worse than none, the room usually knows the code.

## Tool

Default: a Markdown-to-slides tool with slide breaks in the source and an export command (e.g.
Marp) — needs only a runtime and an installed browser. If the project already ships one (e.g.
reveal.js, Slidev, Quarto), use that instead of adding a second. A specific editable file format
(e.g. `.pptx` for further editing) is a different requirement than "a presentation" — check with
the human once that word comes up; some Markdown tools export it as images rather than editable
text, others need their own install for real text slides.

## Steps

1. **Clarify purpose, audience, duration** — in that order, they shape everything else. Missing
   one of the three: ask, don't start.
2. **Read material instead of inventing it:** `README.md`, `docs/project/` (architecture,
   decisions, status), the project's open work. What's nowhere documented isn't worth a slide, or
   needs to go into the docs first.
3. **Lay out an outline before any slide exists** — title per slide, one line of core message,
   estimated speaking time. The human cuts here, not on the finished deck. Rule of thumb: three
   minutes per slide is typical, one per minute is too fast.
4. **Write the slides**, one statement each. Explanation goes into speaker notes, not the slide —
   or the room reads instead of listening.
5. **Diagrams as text** (e.g. Mermaid, or an exported SVG). No screenshots of code or terminals —
   they go stale and are unreadable from the back row; real code in a block of ten lines or less.
6. **Render and look at it** — an export has to have run once before anything counts as done. A
   live demo adds step 7.
7. **A live demo is a run sheet, not a slide:** setup, steps in presentation order, and per step
   what can go wrong and what gets shown instead. Rehearse it fully once before it's ready.
8. Evidence (export ran without errors, path of the produced file), then `act-commit`.

## Filing

Source: `docs/presentation/<name>.md`, versioned; images next to it. Output into a gitignored
build folder — generated HTML/PDF/`.pptx` don't belong in git, they regenerate in seconds. New
files get listed in the project's documentation index with the usual dated-status header.

## Limits

- No deck without purpose, audience, and duration.
- No claim without a source in the repo; if the docs are stale, fix them first.
- No rebuild of a company template from an existing `.pptx` — fonts, colors, logo are the human's
  call, as a theme or not at all.
- No text walls; a slide over roughly six lines gets split, or the text moves to the notes.
- The assistant doesn't give the talk — it delivers slides, notes, and the run sheet.
