---
name: act-design-build
description: Implement a component or page against a template and check the result yourself in the browser - in rounds, until it fits. Use when asked to build a component from a screenshot, implement a chosen variant, or turn a page design into code.
---

# Implement an interface and check it yourself

Implements a component or page in the **real project code**, then compares the result against its
template itself — as many rounds as needed, at most three. Template: a screenshot, a variant from
`act-design-ideas`, a web link, or a description. Unlike "just build it", this checks its own
result before handing it over — without that loop, code comes back plausible-looking and off in
the browser.

## Prerequisite

Say up front whether the self-check is possible: a browser-automation tool plus a way to start the
project locally is the normal case (may need a one-time browser install); an interactive browser
session the assistant can drive directly works too, without a test setup; neither means the skill
runs **without** the check loop — say "implemented", not "implemented and checked".

## Steps

1. **Clarify assignment and template.** What gets built, where it lands, what the template is. A
   web link: screenshot it, don't fetch it as text. A variant from `act-design-ideas`: read its
   HTML file and screenshot.
2. **Read rules and inventory first:** `docs/project/coding_rules.md`; existing components — the
   most common mistake in AI-built interfaces is rebuilding what the library already has; the
   project's color/spacing/type tokens instead of hard-coded values.
3. **Implement** (`builder` role, or the live conversation for one small component). States
   (loading, empty, error) considered, accessibility not skipped (`alt`, focus order, contrast).
4. **Check — the core step:** start the project, open the target page, screenshot it (desktop
   1280px, mobile 390px). Put it next to the template and name what differs: spacing, proportions,
   alignment, color, line breaks, overflow. Read the browser console — an error there counts even
   if the image matches.
5. **Fix, at most two more rounds**, re-checking after each. Still off after the third: **stop and
   report** what fits, what doesn't, why — a fourth round rarely beats a short question.
6. **Prove and close:** required checks (`docs/ai/config.md` § commands), result screenshot filed,
   deviations left on purpose named, then `act-commit`.

## Limits

- The check loop compares images; whether the result is *good* is the human's call — a design
  question found along the way gets asked, not decided.
- At most three rounds; needing more means the assignment was cut too large.
- No side rebuild — anything else noticed goes to `docs/ai/work/backlog/`.
- Check screenshots are throwaway, in a gitignored scratch folder; only one that documents a
  decision moves into the repo on purpose.
