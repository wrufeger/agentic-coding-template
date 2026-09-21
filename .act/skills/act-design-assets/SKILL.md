---
name: act-design-assets
description: Produce graphics that stay in the project - logo, icon set, illustration, favicons - as hand-written SVG or through an image model, checked and placed in the repo. Use when asked to design a logo, icons, a favicon set, or a product image.
---

# Produce graphics

Produces image files meant to stay in the project: logo, icon set, illustration, favicons,
placeholder images. Unlike `act-design-ideas` (throwaway variants for discussion), the result
lands **in the repo**.

## First: which path?

The assistant writes code and text, not raster images. Logo, icon, symbol, diagram, or geometric
illustration: **hand-written SVG**, no prerequisite, it's code. Photo, product image,
photorealistic scene, or painted illustration: **an image model via MCP**, needs a configured
server and costs per image. Missing a server for the second case: say so and name the candidates
from the project's MCP server catalog — don't hand back an SVG that looks like a placeholder and
call it a product image.

## Before a logo: the rights question

State this once and record the answer as an ADR before a logo is built: purely AI-generated work
is not automatically copyrighted (human authorship is generally required), so a logo nobody holds
rights to can be used by anyone else — a real problem for a brand, usually not for an internal
symbol; providers differ on commercial use and rights transfer, check the specific model's terms;
a hand-written SVG faces the same question but is easier to settle, since editing and choosing
among drafts is the human contribution. For a logo meant to carry a brand: use the draft as a
starting point, have a human finish it.

## Steps for SVG (logo, icons, illustration)

1. Clarify: what, for what purpose, what mood, which colors (project tokens, not invented ones),
   what sizes; for icons: how many, which grid (16/24/32px), stroke or fill.
2. Check the inventory: an icon set already in the project means nothing gets redrawn that's
   already there — only what's missing, in the same style.
3. Two or three visibly different drafts: `viewBox` set, no fixed `width`/`height` on the root,
   colors via `currentColor` where possible, no embedded raster images, text as paths (a font
   glyph is missing at render time otherwise).
4. Look at them, don't guess: a screenshot per draft, light and dark background, at target sizes —
   an icon smearing at 16px is unusable even if it's fine at 512px. Check contrast on color.
5. The human picks, then optimize (e.g. `svgo`); look again afterward, since an optimizer
   occasionally shifts rendering.
6. Place per project convention and wire it in. Favicons as a **set** — 16, 32, 180 (Apple touch),
   512 (PWA) — plus the matching config entries, never a single file.

## Steps for raster images (image model)

1. Check whether an image generator is configured (project's MCP server catalog); if not, name
   the candidates, that cost applies per image, and that license terms need checking — don't set
   one up without agreement.
2. Name cost and rights upfront, not afterward.
3. Build a prompt from the assignment, generate two to four variants, put them to a decision.
4. Post-process: resize to target dimensions, save as WebP or AVIF (PNG as fallback only), check
   file size — a 4MB product image doesn't belong in the repo.
5. Record provenance (model, prompt, date) in `docs/project/decisions.md` or a text file next to
   the image, or later nobody can reconstruct the conditions it was made under.

## Limits

- No large raw files in the repo (PSD, AI, uncompressed PNG) — they bloat git and don't diff.
- No photorealism attempted in SVG — the file gets bigger and looks worse than a small WebP.
- No recreating another brand's mark — a logo "in the style of" a known brand is a legal problem.
- The skill doesn't decide the design — it delivers drafts and evidence; the human picks.
