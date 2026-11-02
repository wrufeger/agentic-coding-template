---
name: act-seo
description: Use when asked to check SEO, why pages are poorly found in search, Lighthouse scores, page speed, or before launching a site. Default is a code check (metadata, headings, links, hreflang, structured data, duplicates, robots.txt, sitemap); on request also a crawl and Lighthouse run against the production build (--live) or the public URL. Fixes only what is approved.
---

# Check SEO

Checks how a page is found and shown in search. Three levels, each its own switch; the code check is the
default and the other two run only when asked for ("live", "production build", "the public site").

| Level | Script | Needs |
| :--- | :--- | :--- |
| Code (default) | `python .act/scripts/seo_check.py` | nothing; reads HTML, templates, Markdown |
| `--live`: production build | `seo_crawl.py`, then `seo_lighthouse.py` | a running build on the test port, Node and Chrome for Lighthouse |
| Public URL | `seo_crawl.py --public`, `seo_lighthouse.py --pagespeed` | the site on the internet; a PageSpeed key |

## Code check

1. **Run it.** `python .act/scripts/seo_check.py` (`--json`, `--root` for a sub-project). It names the stack and
   the pages it read; zero pages means a CMS or database builds the site — say so and stop (a live run can
   still work).
2. **Read the notes first.** Markdown generators decide the routes, so internal links are then not checked; a
   stack that generates `sitemap.xml` or `robots.txt` at build time is not reported as missing them.
3. **Judge the findings**, heaviest first:
   - `missing-title`, `empty-title` (error); `missing-description`, `duplicate-title`,
     `duplicate-description` (warning): each page needs its own; a duplicate is usually a layout default.
   - `missing-h1`, `multiple-h1`, `heading-order`; `missing-lang` (also an accessibility defect);
     `img-alt-missing` (decorative images get `alt=""`); `img-size-missing`; `missing-viewport`.
   - `broken-internal-link`, `sitemap-url-missing-page`, `orphan-page`: check the route is not generated
     dynamically before calling it broken.
   - `duplicate-content`: only `main` text is compared; the canonical decides which copy is the original.
   - `hreflang-*`, `jsonld-invalid|incomplete`: both are checked for form, not for what Google accepts.
   - `translation-*`: come from `i18n_check.py`, the engine of `act-check-translations`; do not re-run it.
   - `robots-blocks-all`: stops indexing entirely, often a staging leftover; ask before changing.
   - `client-rendered` (info): crawlers may see an empty page — structural (server-side rendering,
     prerendering): a backlog entry, not a quick fix.
   - `missing-canonical`, `missing-og`, `title-length`, `description-length`, `noindex`,
     `page-not-in-sitemap`, `robots-no-sitemap` (info): improvements; `noindex` may be intended.

## Live run (`--live`) and public URL

Steps, the server commands and the way to stop the server: `references/live-run.md`. In short: build the
production build (`run` in `docs/ai/config.md`), start it on the test port (`R-safe-dev-server`), crawl it,
measure one URL per page type with Lighthouse, stop the server by PID after checking port and command line.
The public run sends the URL to Google (PageSpeed Insights) — say so before the call; the key comes from
`PAGESPEED_API_KEY` only, never from an argument or a file you read.

## Report, fix, measure again

- **Separate points from defects.** Lighthouse points (`points`, `noise`) are a measure, not a task; real
  defects (failed axe audits, broken links, missing metadata, slow TTFB, large CLS) are the findings.
  Lighthouse is a lab measurement: localhost TTFB says nothing about the hosting, field data (CrUX) exists
  only for a public URL with traffic.
- **List what you propose** per page group — what, where, fix — and ask. Texts for titles and descriptions are
  the human's call; do not invent marketing copy into the files. Fix only what is approved.
- **Measure again** after the fix: until every category is 100 or each deviation is explained. Count a change
  only when it is larger than the spread of the runs (median of three).
- **Never chase 100 at a cost:** do not remove analytics, inline everything, or trade accessibility or
  readability for points; name such a trade-off and let the human decide. Accessibility 100 means only that
  the axe audits pass (about a third of WCAG).
- Show before/after counts, then `act-commit`.

## Limits

- The code check reads files only; the live and public runs measure one build or one URL, not rankings. No
  Search Console data.
- Template files are read with an HTML parser that ignores template logic: a `<title>` built from a variable
  is accepted, a head split across partials is a fragment and not checked. Structured data is checked for
  form, not against search-engine rules.
- Route detection is file based; dynamic and rewritten routes may be reported as broken links although they
  work. The crawl sees the rendered site and does not have this limit.
- Hand checks for accessibility (keyboard, screen reader, contrast in context) stay with `act-a11y`; axe
  findings in the Lighthouse report need no second run. Translations: `act-check-translations`.
