# Adopting the old configuration (step 5)

Read from step 5 of `SKILL.md` when the project has an old `AI-CONFIG.md` or `.claude/template.json`, and for the hand comparison of `docs/ai/config.md`.

It reads the old `AI-CONFIG.md` (at its place, or its legacy copy; `--source <file>` for another
one) and the old `.claude/template.json` values, and sets known keys in `docs/ai/config.md` only
where the value is still an `init.py` default — a value already set is reported, never
overwritten. The old `Coding-Guidelines` list checks those rule sets (plus what their `requires:`
pulls in) with their group lines in `docs/project/coding_rules.md`; that is no merge of the old
coding rules — step 6 still does that. Everything else — unknown keys, values without a
counterpart, every free-text passage with its line numbers — lands in
`<dir>/.act-local/adopt/config-report.md` (no title of its own: the inbox entry of step 6 gives
it one). It also brings the init notes up to date (`for:` the adopted owner as the workspace identity, the
"uses defaults for" line reduced to what is still a default, a section naming what it set). Without any old configuration (no `AI-CONFIG.md`, no `template.json` values) it prints
"nothing to adopt" and exits 0 — the normal case for a project that never used the old
template; there is no report and no config inbox item then.

Then compare `docs/ai/config.md` with the old project by hand and correct it (orchestrator):
`tools`, `language-chat`, `language-docs`, `stack`, `commands`, `owner`, `mode`. A lint,
typecheck or test command that names a path the adoption removes (a predecessor script on
`delete`/`legacy`) is set as given and flagged in the report ("command refers to a path that the
adoption removes"): settle it with the owner — drop it, or point it at what replaces it.
Where step 4 passed no `--language-docs`, `adopt_config.py` sets `language-docs` from the old
template's `Sprache` row (`Deutsch` -> `de`); an old `AI-CONFIG.md` without any language row gets `de`
too, marked as an assumption in the report (the old template was always German) — confirm it with
the owner. A language passed in step 4 (`--language-docs`/`--language-chat`) is kept as given, no
assumption and no overwrite. It never sets `language-chat` (stays as passed, else `auto`) or `mode`. A `language-docs` other than English leaves
`docs/ai/inbox/U<n>-translate-scaffold.md` (from `init.py` when step 4 passed the
language, else from `adopt_config.py`, or from you by hand if you set it yourself: `init.py` wrote
the scaffold in English, marked `act:default`) — translate that
scaffold once as `R-work-language` describes, never the adopted content, whose translation is a
separate assignment offered in the report, done only on request. This has to be right before
step 6 and 7: `--finish` chooses the bridges by `tools` (without `claude-code` there, an adopted
`CLAUDE.md` is removed instead of becoming the bridge), and `mode` decides whether an entry
without a kept id gets a new id now (`solo`) or none yet (`team`).
