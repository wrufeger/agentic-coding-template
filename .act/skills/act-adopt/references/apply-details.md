# What apply does (step 4)

Read from step 4 of `SKILL.md` when `--apply` refuses, fails, or its recorded state needs explaining.

Refuses on an existing `act-adopt` branch, a detached HEAD, or a working tree that is not clean
(only `.act-local/` may be untracked). Creates and switches to `act-adopt`, backs up
`.claude/settings.json`, moves every `legacy` row byte-identical to
`docs/ai/work/archive/legacy/<old path>` — and there too every `adopt` row that sits where
`init.py` writes a file itself or carries the name of a template skill/agent (a `keep` row at
such a place stays and `init.py` leaves it; a `keep` row colliding by skill/agent name moves; a
`delete` row there is removed right away) — then runs
`init.py --target <dir> --non-interactive --no-commit` (with the languages given above) and stages
the moves. `CLAUDE.md` and
`AGENTS.md` stay in place until `--finish`. `<dir>/.act-local/adopt/state.json` records the
result: `moved` (old path -> legacy path), `removed_at_apply` (`delete` rows removed before
`init.py`), `created` (the files `init.py` wrote where nothing was versioned before — never a
git-ignored one; those are in `created_ignored`, for `--abort` only), `dirty_after_apply` (every
versioned file that differs from the start: the moves, and what `init.py` wrote over versioned
paths — `.gitignore`, a moved or removed place it filled again), and the hash of each target that
existed. The accounting counts a legacy copy only when it is on disk **and** in the Git index,
and it counts every `adopt` row: one `--apply` moved first stands as `adoption pending`, marked
`into itself` where its target is its own path (`--finish` counts it `at target`).

Run again after success, it prints the recorded state and exits 0. Any failing Git call stops the
run without an accounting: state `stage-failed` (the moves could not be staged) or `init-failed`
(`init.py` itself failed). A second `--apply` is refused then — the way back is `--abort`, not a
retry; fix the cause (a path too long: `core.longpaths`, step 2) and start again at step 1.
