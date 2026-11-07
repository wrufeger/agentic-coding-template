# Commit groups of the adoption (step 8)

Read from `SKILL.md` step 8. The orchestrator commits, by pathspec, on `act-adopt`.

`adopt.py` never commits. Each group below is one `git add -- <paths>` (only paths that exist)
and one `git commit -m "<message>" -- <paths>` (all of them). A path `--apply` or `--finish`
removed is already staged as a removal: `git add` fails on it ("did not match any files"),
`git commit -- <path>` takes it. A git-ignored file is never added — not with `-f` either: nothing
under `.act-local/`, no `__pycache__/` (`created` lists none). In this order:

1. **Legacy moves** — `docs/ai/work/archive/legacy` plus the old paths in `state.json`'s `moved`
   that are no longer on disk (staged as renames by `--apply`, nothing to add). A moved path that
   `init.py` filled again is not a rename; it belongs to group 2 or 3.
2. **The template layer** — every path in `state.json`'s `created` and `dirty_after_apply`, plus
   the `removed_at_apply` paths; except anything under `.act-local/` (git-ignored) or
   `docs/ai/work/archive/legacy/`, group 1's paths, and table targets. That is `.act/`, bridges,
   skeleton, tool copies, `.act-lock.json`, the init notes in the inbox together with the
   scaffold files translated in step 7 and the translate-scaffold todo at its archive path, never
   its old inbox path (it was never committed there, so git finds no such pathspec) (all
   about the scaffold, not about old content; step 5 may have changed the init notes; a
   translated file that is a table target goes to group 3), `.gitignore`, the template copies
   now standing where an old unit of the same name was moved or removed (with the removal of that
   unit's other files), and `.claude/settings.json` as it is now — `init.py`'s merged hooks and
   the entries `--finish` or the orchestrator removed in step 7 in one commit, since a pathspec
   commit always takes the whole file (the report lists the removed entries).
3. **One commit per target** — an `adopt` row's `target` files (entries, proposals,
   `docs/ai/config.md`, `docs/project/coding_rules.md`, `docs/README.md`,
   `docs/ai/local/<unit>`); for a `legacy` row, the entry files `entries-map.json` lists under its
   `source_path` (they are nobody's table target, so they are easy to miss). A path that is both
   moved and a target — `docs/README.md` or `docs/project/coding_rules.md` adopted into itself —
   goes here with its source, not into group 1 or 2 (its legacy copy is in group 1). Where several
   sources feed one target (five `project-doc` files into `docs/project/architecture.md`, several
   work files into the same entry set), that is one commit for the target, not one per source —
   name the sources in its message. Rows without a shared target stay one commit each.
4. **What `--finish` did** — `state.json`'s `bridged` and `removed_at_finish` paths, the tool
   copies it printed for own units (`skills: <path>: created`, role bridges), and the adoption
   report (`state.json`'s `report`).
5. **References and the docs index** — the files under `docs/project/`, and `docs/README.md`, whose links `--finish`
   bent: `git -C <dir> status --porcelain -- docs/project docs/README.md` lists them as modified;
   one that already belongs to group 2 or 3 (a table target, a file `init.py` wrote) stays there.
   `--finish` only bends links: **a new `docs/project/` target gets no line in the docs index
   `docs/README.md`** — add one per new file by hand, or in `act-commit` step 5 ("Docs index: new
   files go into `docs/README.md`"), before this commit, and count `docs/README.md` here.
6. **Baseline findings** — only when step 7b booked: the backlog entry files `adopt_baseline.py --book`
   created (`git -C <dir> status --porcelain -- docs/ai/work/backlog` lists them as untracked; they are
   nobody's table target). Last in the order, since 7b runs after the others; the booking file under
   `.act-local/` is git-ignored and not added.

Before the first commit, check the grouping: every line of
`git status --porcelain --untracked-files=all` (both sides of a rename) falls under exactly one
group. Afterwards `git status` shows nothing but git-ignored files; the owner reviews
`act-adopt` and merges it.
