---
name: act-seo
description: Check a project's pages for basic search-engine optimization in the code - title and description, headings, lang, canonical, Open Graph, image alt text, internal links, robots.txt and sitemap - and work through the findings. Use when asked to check SEO, why pages are poorly found, or before launching a site.
---

# Check SEO

Checks what the code decides about how a page is found and shown in search results. Code only: the
script reads HTML, templates and Markdown pages and does not fetch anything. How the rendered page
looks, how it is ranked, and Search Console data are not covered.

1. **Run the check.** `python .act/scripts/seo_check.py` (`--json` to process the result, `--root` for a
   sub-project). It names the stack it detected and how many pages it read; zero pages means the
   site is built from something it does not read (a CMS, a database) — say so and stop.
2. **Read the notes first.** Markdown generators decide the routes, so internal links are then not
   checked; a stack that generates `sitemap.xml` or `robots.txt` at build time (`package.json` or
   config names it) is not reported as missing them.
3. **Judge the findings**, heaviest first:
   - `missing-title`, `empty-title` (error); `missing-description`, `duplicate-title`,
     `duplicate-description` (warning): every page needs its own; a duplicate usually means a layout
     default that a page forgot to override.
   - `missing-h1`, `multiple-h1`, `heading-order`: one `h1` per page, levels without jumps.
   - `missing-lang`: also an accessibility defect.
   - `img-alt-missing`: meaningful images get a description, decorative ones `alt=""`.
   - `broken-internal-link`, `sitemap-url-missing-page`: links to nothing; check the route is not
     generated dynamically before calling it broken.
   - `robots-blocks-all`: stops indexing entirely — often a leftover from staging; ask before changing.
   - `client-rendered` (info): the page body is built in the browser; crawlers may see an empty
     page. A structural question (server-side rendering, prerendering) — a backlog entry, not a quick fix.
   - `missing-canonical`, `missing-og`, `title-length`, `description-length`, `noindex`,
     `page-not-in-sitemap`, `robots-no-sitemap` (info): improvements; `noindex` may be intended.
4. **List what you propose** per page group — what, where, fix — and ask. Texts for titles and
   descriptions are the human's call; propose, do not invent marketing copy into the files.
5. **Fix what is approved**, re-run, show before/after counts, then `act-commit`.

## Limits

- Code only, first version: no rendered-page checks (no browser), no Search Console, no ranking,
  no speed or Core Web Vitals (`act-perf`), no structured-data validation.
- Template files are read with an HTML parser that ignores template logic: a `<title>` built from a
  variable is accepted, a head split across partials is seen as a fragment and not checked.
- Route detection is file based (`pages/`, plain HTML); dynamic and rewritten routes may be reported
  as broken links although they work.
- Accessibility beyond alt text and `lang` is `act-a11y`.
