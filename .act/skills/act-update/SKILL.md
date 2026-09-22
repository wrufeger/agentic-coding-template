---
name: act-update
description: Pull a newer template state into the project - review the diff, give consent, then let update.py replace .act/, refresh copies, run migrations, and hand off to the doctor. Use to check for or apply a template update.
---

# Update the template

Thin wrapper around `python .act/scripts/update.py` — nine steps, always in the same order (full
option list in the script's own header comment). No merge, no conflicts to resolve by hand: steps
1-3 only fetch, diff, and report; nothing from the fetched state runs before consent.

## Steps

1. `python .act/scripts/update.py --plan` — shows the `.act/` diff (rule/coding IDs individually)
   and describes steps 5-9, writes nothing. Share the summary with the human.
2. Clean working tree first (`git status`) — an unfinished task closes via `act-commit` before an
   update starts.
3. **Consent before step 5**, where `.act/` gets replaced: rerun the command without `--plan`, or
   pass `--yes` only once the human already agreed. If the project edited `.act/` itself since the
   last update, `--on-local-changes rescue|discard|abort` picks the answer up front (`rescue`
   moves the edits to `docs/ai/local/` first) instead of a prompt mid-run.
4. The script itself refreshes template-owned skill copies (unchanged → replaced, project-edited →
   kept and reported), runs any due migrations, and hands off to `doctor.py` — its findings land in
   `docs/ai/inbox/`, never as a silent fix.
5. `.act-lock.json` is rewritten and a commit made automatically, unless `--no-commit` was given —
   then commit by hand after review.
6. A journal line with the base-commit change and the finding count (`R-work-record-now`).
7. A template bug noticed along the way (wrong or missing file, dead rule or mechanism, two rules
   that contradict each other): an `act-feedback` entry right away, per `act-feedback` § immediate
   trigger — that trigger overrides the usual feedback cadence.

## On a branch other than the default

The mechanism itself warns and does not refuse (`update-branch-hint` in `docs/ai/config.md` §
Checks); teams still prefer one person pulling the update and opening a PR over two people pulling
it on separate branches the same day.

## `.act/` pulled in some other way

There is no "template" git remote to update from — its address lives only in `.act-lock.json`'s
`template.source` (set by `init.py`, never a remote in the project itself). If `.act/` ever got
replaced by something other than this script (a plain `git pull` of the shared history some older
projects still keep, or a manual copy), a normal run notices it on its own — step 3 finds no diff,
then it resumes instead of reporting "nothing to update", no rescue question. `--catch-up` does the
same without a fetch, for when there is nothing new to pull first; it refuses if `.act/` no longer
matches its own `MANIFEST.json` (a genuine hand edit, not this case). `dispatch.py` also flags this
state at session start ("pulled in without update.py") — see `update-check` in `docs/ai/config.md`
§ Checks, which also runs a throttled, best-effort daily check for whether the template moved on.

## When not

A task is mid-flight with uncommitted changes: finish it first (`act-commit`), then update.
