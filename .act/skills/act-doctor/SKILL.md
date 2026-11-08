---
name: act-doctor
description: Use to check for drift against the template, after an update, or when asked whether local overrides still make sense. Runs the cheap mechanical checks (stale overrides, dead IDs, orphaned bridges); content checks only on request. Not for performing an update - use act-update.
---

# Reconcile against the template

Two parts, kept apart because of cost: the mechanical half is cheap and runs on its own; the content half needs a
model and runs only on request or for what an update just touched.

## Mechanical (always, cheap)

`python .act/scripts/doctor.py` — what it checks and its options (`--inbox`, `--json`, `--accept ID`,
`--accept-all`): `--help` and the script's header. `update.py` runs it as its step 8; running it again afterwards
is redundant unless something was fixed in between. A stale override is accepted (`--accept`) only once the human
has read the changed template text.

Optional: `agnix`, an external linter for agent files, may be run as a second opinion, never installed unasked
(`R-code-tools`). Its stock rules `XML-001`, `REF-001`, `CDX-AG-005` and `CC-AG-019` raise known false alarms
here (placeholders, `.act/bridges/` sources, the role fields `tier`, `reasoning`, `variant-of`); switch them off
and read the rest as hints. `doctor.py` decides.

## Content (on request, or for rules an update just changed)

For each new or changed template rule ID, compare it against the project's own rules (`[+]` and `replaces`
entries in `docs/ai/rules.md`) — only that cross-product. Same comparison, other direction, for two projects'
own rules on `act-load-settings`. Three findings, three offers, **never a silent fix**:

- **matches** the template rule → offer to drop the project's own rule and check the template one.
- **goes beyond** it → offer to trim the project's rule to the remainder (diff proposed, the wording stays the
  human's).
- **contradicts** it → report only; the project's rule still wins, but the human should know.

Also flag a widely applicable own rule as a template candidate (never sent on its own — `act-feedback`'s consent
and the `feedback` setting govern any send).

## Result

Every finding is an entry in `docs/ai/inbox/`, never a rewritten file (`R-work-record-now`). Many findings of one
kind may be one entry with a list; the fix needs the human's choice per item.
