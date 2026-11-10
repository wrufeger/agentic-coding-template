---
name: act-update
description: Use to check for or apply a newer template version, or when asked which template version is installed or newest ("update the template", "act-update"). Brings in the new version only after you have seen the diff and agreed. Not for checking local drift - use act-doctor.
---

# Update the template

Wrapper around `python .act/scripts/update.py` (options and the ten steps: `--help` and its header). Nothing
fetched runs before consent. Asked which version is installed or newest, run `update.py --versions --short` (the
`/act-version` shortcut) — never answer from memory.

## Channel

`update-channel` in `docs/ai/config.md`: `release` (default) is the newest stable tag, `latest` the tip of the
source's default branch; `--channel` overrides it for one run, `--ref <tag-or-commit>` beats both. A project
already past the newest release keeps its state.

## Steps

1. Clean working tree first; an unfinished task closes via `act-commit`. A project older than `v2.2.0` is refused
   with a message naming the way: set it up again with `act-adopt`.
2. `python .act/scripts/update.py --plan` and share its summary with the human. It changes nothing. Show the
   migration lines (one `<id>: <effect>` line each under `[8/10]`) as they stand before asking for consent;
   never describe a migration from its name.
3. **Consent before step 5** (`.act/` is replaced): rerun without `--plan`, or with `--yes` only once the human
   agreed. If the project edited `.act/` since the last update, ask what to do and pass
   `--on-local-changes rescue|discard|abort` (`rescue` moves the edits to `docs/ai/local/`).
4. A project from before the changelog file is offered `CHANGELOG.md` by migration `007-changelog-file` (the plan
   lists it). Tell the human before step 3 that the row `changelog` = `off` under § Formats in `docs/ai/config.md`
   declines it; `config.py` cannot set a missing row, `.act/skeleton/config.md` shows its shape.
5. The script's findings land in `docs/ai/inbox/`, never as a silent fix; the commit is made unless `--no-commit`.
   Add a journal line with the base-commit change and the finding count (`R-work-record-now`).
6. A template bug noticed along the way: an `act-feedback` entry right away (its immediate trigger).

## `.act/` pulled in some other way

If `.act/` was replaced by a plain `git pull` or a manual copy, a normal run notices it and resumes;
`--catch-up` does the same without a fetch and refuses when `.act/` no longer matches its `MANIFEST.json`.
