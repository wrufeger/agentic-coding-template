# Abort details

Read from the Abort section of `SKILL.md` when `--abort` refuses or something was written after `--apply`.

Without `--force`, `--abort` refuses when a file `init.py` created has changed since `--apply`
(e.g. `docs/ai/config.md` and the init notes after step 5, an edited init note), when a tracked
file has an uncommitted change beyond what `--apply` left, or when something new or changed sits
where a moved unit has to return. A commit on `act-adopt` other than `init.py`'s own refuses it
**with or without `--force`** — take those commits off the branch first, the refusal says how.
With `--force`, the changed files are copied to `.act-local/adopt/aborted/` before they are
removed.

**What `--abort` does not catch:** files written after `--apply` by anything but `init.py` —
`docs/ai/inbox/U<n>-translate-scaffold.md` from step 5, and everything the content step added:
entries under `docs/ai/work/`, `docs/ai/inbox/`, proposals under
`docs/ai/proposals/`, copies under `docs/ai/local/`. They neither block `--abort` nor are removed
by it: it ends with exit 0 and lists them as "left in place (not created by adopt/init): ...",
untracked on the base branch. Move them out of the way (e.g. into
`<dir>/.act-local/adopt/aborted/`) or delete them — a new `--apply` refuses the unclean tree, and
a new scan would sight them as sources. Before a new attempt, move `table.json` and
`entries-map.json` aside too; it starts again at step 1.
