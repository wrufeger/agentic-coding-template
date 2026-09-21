---
name: act-doctor
description: Reconcile project and template state - mechanical checks after every update (stale overrides, dead IDs, orphaned bridges), content checks only on request or for rules an update just changed. Use to check for drift against the template, after an update, or when asked whether local overrides still make sense.
---

# Reconcile against the template

Two parts, kept separate because of cost: the mechanical half is cheap and runs on its own; the
content half needs a model and runs only on request or for what an update just touched.

## Mechanical (always, cheap)

`python .act/scripts/doctor.py` (add `--inbox` to also write `docs/ai/inbox/<date>-doctor.md` when
there are findings; `--json` for machine output; `--accept ID [...]` / `--accept-all` to record a
stale override's current template text as the accepted baseline). Runs `rules.py --validate` for
both areas plus: dead override/off IDs, a disabled coding set whose `use:` target is gone, an
override/off whose template text changed since it was last accepted, duplicate skills/agents/
scripts from earlier updates, broken `act:ref` references and bridge targets, and a script/agent/
skill under `docs/ai/local/` or `.claude/` that no generated copy or bridge explains. `update.py`
calls this itself as its step 8 — running it again by hand afterward is redundant unless something
was fixed in between.

## Content (on request, or for rules an update just changed)

For each new or changed template rule ID, compare it against the project's own rules (`[+]` and
`replaces` entries in `docs/ai/rules.md`) — only that cross-product, not everything against
everything. Same comparison, other direction, for two projects' own rules on `act-load-settings`.
Three findings, three offers, **never a silent fix**:

- **matches** the template rule → offer to drop the project's own rule and check the template one.
- **goes beyond** it → offer to trim the project's rule down to the remainder (diff proposed, the
  wording stays the human's).
- **contradicts** it → report only, change nothing — the project's rule still wins (`ADR-5`), but
  the human should know the template now thinks differently.

Also flags: a widely-applicable own rule as a template candidate (never sent on its own —
`act-feedback`'s consent and `Feedback` setting in `docs/ai/config.md` still govern any send), and
a `docs/ai/proposals/` entry sitting unanswered past its threshold — **gap:** that threshold isn't
defined anywhere yet, and `doctor.py` doesn't check `proposals/` at all today.

## Result

Every finding is an entry in `docs/ai/inbox/`, never a rewritten file — `R-work-record-now`
applies. A widespread mechanical finding (e.g. many dead IDs after a large rule reshuffle) can
still be summarized as one inbox entry with a list, but the fix itself needs the human's choice per
item above.
