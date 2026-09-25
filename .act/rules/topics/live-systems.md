# Access to live systems

Detail page for `R-safe-approval` (`.act/rules/shared/10-safety.md`). Read this whenever a task
reaches beyond the repo into a reachable system: a server over SSH, a database, a service's API, a
container host, a router, a smart-home or monitoring instance.

## Reading is the default

Status lookups, inventories, logs, reading out a configuration — always allowed, no approval
needed.

## Writing needs a dated approval

A write happens only with the human's explicit, dated approval for exactly this purpose. Record
the approval in the journal (`docs/ai/work/ledger/`, via `entries.py`) with its date; it does not
carry over to the next similar case on its own — a new case needs a new approval.

## Before any changing action

Save the current state first — a backup, an export, a copy of the configuration file — and name
the way back. No way back, no change.

## Preview before a destructive or large change

Summarize first exactly what is about to happen (affected objects, count, side effects), wait for
confirmation, then execute — never the other way round.

## Recurring writes go through a script

A write that repeats runs through a reviewed script under `docs/ai/local/scripts/` (readable, repeatable,
not a freely worded one-off command) instead of changing command lines each time.

## Making something visible is its own approval

Creating a draft is not publishing it, and setting a status is not proof of publication. Making
something visible to others (draft → published) needs its own dated approval, separate from the
approval to create the draft. Write exactly the approved scope — approved 3 of 7 items means write
3, not 7. Afterwards, confirm with an independent piece of evidence (a fresh read, an outside
view), not with the tool's own success message. If an already-executed action looks wrong, never
"correct" it with a second unapproved action — ask first.

## Deletion, production deployment, rights changes

Permanently deleting data or accounts, deploying to production, and changing rights or access are
exactly the cases `R-safe-approval` names — they always need the dated, purpose-specific approval
above, never a blanket one carried over from something else, and never as a side effect of an
otherwise-approved change.
