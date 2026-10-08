---
name: act-design-ideas
description: Use when asked for design ideas, variants for a component or page, or what something could look like, before any code exists. Produces three to four preview images from a description, screenshots or links. Not for building the chosen one - use act-design-build.
---

# Design variants to choose from

Produces **three to four** visibly different drafts of a component or page as images to compare.
The human decides, then `act-design-build` builds the chosen one. Images, not descriptions:
"airier" or "more modern" can be argued forever; two screenshots side by side settle it in
seconds.

## Prerequisite

What can produce the images: a browser-automation tool in the project (e.g. Playwright, the
normal case), or an interactive browser session the assistant can drive directly (works, slower,
less reproducible). Neither: no images possible — say preview images need a browser tool and
offer to set one up, don't fake it with descriptions called "drafts".

## Steps

1. **Clarify the assignment** (briefly, in conversation): what exactly (component, page,
   excerpt), what for (purpose, content, audience), templates (description, screenshot, web link,
   existing page), range (close to the current look, or something unfamiliar too).
2. **Read the templates.** A screenshot file is read directly (JPEG/PNG/GIF/WebP, max 8000×8000px
   and 10MB, unusable below ~200px edge length); a web link is opened and screenshotted — fetching
   it as text captures the HTML, not the look. Ask what specifically is liked if it isn't said;
   "the card spacing" is usable, "looks good" isn't.
3. **Read the existing project first** (delegate to `explorer`): component library, color/spacing
   tokens, comparable pages already in use. Ignoring them gets expensive later. Result ≤ 20 lines.
4. **Build the variants:** one self-contained HTML file per variant, in a gitignored scratch
   folder, using the project's own CSS/tokens and real sample data. Variants must differ in
   something recognizable (layout, density, hierarchy), not just color. One line per variant: what
   differs, who it speaks to. Independent variants build in parallel, one `builder` per variant.
5. **Screenshot each variant** — at least desktop (1280px) and mobile (390px) — against the local
   files, no dev server needed.
6. **Lay out an overview** with all screenshots side by side, numbered, with the reasoning from
   step 4. Name the file path in chat; a terminal can't show images.
7. **Put it to a decision:** one sentence per variant, then one question — "Which direction? a) 1
   b) 2 c) 3 d) mix — which parts?" A stated preference is fine, a pre-made decision isn't.
8. **Record the outcome** in `docs/project/decisions.md` if it holds beyond this case (e.g. "lists
   become cards"); otherwise handing off to `act-design-build` is enough.

## Limits

- No project code — only the scratch folder; `act-design-build` implements.
- At most four variants; more becomes undecidable.
- The scratch folder is gitignored; a variant that matters moves in as one file, not the folder.
- Steps 1 and 7 need the live conversation; only building the variants in step 4 is delegated.
