# Commit groups of the adoption (step 8)

Read from step 8 of `SKILL.md`. One `git add -- <paths>` (existing paths only; a path `--apply` or `--finish` removed is
already staged, `git commit -- <path>` takes it) and one `git commit -m "<message>" -- <paths>` per group, never a
git-ignored file (not with `-f` either), in this order:

1. **Legacy moves**: `docs/ai/work/archive/legacy` and the old paths of `state.json`'s `moved` no longer on disk. A moved
   path `init.py` filled again belongs to group 2 or 3.
2. **Template layer**: `created`, `dirty_after_apply` and `removed_at_apply` of `state.json`, minus `.act-local/`,
   legacy, group 1 and table targets: `.act/`, bridges, skeleton, tool copies, `.act-lock.json`, init notes, scaffold
   files translated in step 7 (a table target goes to group 3), the translate-scaffold todo at its archive path only,
   `.gitignore`, template copies now standing where an old unit was moved, and `.claude/settings.json` whole, since a
   pathspec commit takes the whole file.
3. **One commit per target**: an `adopt` row's `target` files; for a `legacy` row the entry files `entries-map.json`
   lists under its `source_path`. A path both moved and a target (`docs/README.md` adopted into itself) goes here. Several
   sources into one target: one commit, sources named in the message.
4. **What `--finish` did**: `bridged`, `removed_at_finish`, tool copies of own units, the adoption report.
5. **References and docs index**: `git -C <dir> status --porcelain -- docs/project docs/README.md` lists what `--finish`
   bent. A new `docs/project/` target gets no line in `docs/README.md` from `--finish`: add one by hand before this
   commit and count `docs/README.md` here.
6. **Baseline findings**: the backlog entries `adopt_baseline.py --book` created, only when step 7b booked.

Before the first commit, every line of `git status --porcelain --untracked-files=all` (both sides of a rename) falls under
exactly one group.
