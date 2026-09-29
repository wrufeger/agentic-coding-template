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

## Repo host and issue tracker

Creating a pull/merge request, an issue or a comment, and closing one, are writes to a live system
(GitHub, GitLab) and follow the rules above with these specifics:

- **Approval:** a preview plus the human's explicit "yes" in the chat, per action, is the dated
  approval for exactly that action. Show what will be sent — target, title, text, labels — and write
  exactly that, nothing more; one "yes" covers one action, never the next one. A draft PR/MR is not
  a published one: making it ready is its own "yes" (see "Making something visible" above), and `forge.py` cannot do it —
  the human in the web interface, or the orchestrator after that "yes".
- **Way back:** close it, never delete it (`forge.py close-pr`, `close-issue`); a comment stays and
  is followed by a correcting one (or edited in the web interface), once the human agrees — closing
  does not undo a comment. No backup is needed (see "Before any changing action"): these writes
  create something new and overwrite nothing.
- **Journal:** right after the action, an entry with the link (`entries.py new ledger ...`, the
  link `forge.py` printed) and the approval — the "yes" in the chat with its date and what it
  covered.
- **Script:** `.act/scripts/forge.py` is the vetted script for these recurring writes. It shows a
  preview and sends only with `--apply`, and never takes the token from the command line. This
  differs on purpose from "Recurring writes go through a script" above, which names
  `docs/ai/local/scripts/` — a template-shipped script counts as vetted, no copy needed there.
- **Push:** pushing the branch a PR/MR needs is the orchestrator's alone, after its own "yes".
  A worker never pushes, and never applies these writes.
- Reading (projects, issues, PR/MR lists) stays free. Probing which access exists is
  `.act/scripts/integrations.py` (`act-integrations`), which never tries a write.

## Deletion, production deployment, rights changes

Permanently deleting data or accounts, deploying to production, and changing rights or access are
exactly the cases `R-safe-approval` names — they always need the dated, purpose-specific approval
above, never a blanket one carried over from something else, and never as a side effect of an
otherwise-approved change.
