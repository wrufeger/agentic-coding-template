# What finish does (step 7)

Read from step 7 of `SKILL.md` after `--finish --plan`, and for the check of the result.

What `--finish` does after that, all shown first by `--finish --plan` (nothing written but the
reference list):

- **Settings entries on removed scripts.** A hook command or `Bash(...)` permission rule in
  `.claude/settings.json` whose **executed** script (the command's first word, or the word after
  `python`, `bash`, `node`, …; a bare, `./` or `$CLAUDE_PROJECT_DIR/` path) this adoption removed
  — a `delete` or `legacy` row — is removed, an emptied hook group or event with it; everything
  else stays byte for byte. A script that is only an argument, a `Read`/`Edit`/`Write` rule and an
  entry on a script still on disk are never touched. The report lists these under its own settings
  heading instead ("Remove it by hand, or check" / German "Von Hand entfernen, oder prüfen"):
  every entry when the file's layout cannot be reproduced exactly, an entry whose
  script was already missing before the adoption (it stays) or went with an `adopt` row, a
  `statusLine` on such a script, and every entry in `.claude/settings.local.json` (a local file,
  the owner's). The file is left unstaged (group 2 in step 8).
- **The `act:default` mark** goes from line 1 of every `adopt` target that changed since
  `--apply` (it now holds adopted content, no scaffold), a file below a folder target included —
  except `docs/ai/config.md`: only values were taken over there, its text stays the template's
  scaffold and so stays on the translation list.
- **Dead references in `docs/project/` and `docs/README.md`** to a path that is gone — or to a
  folder the adoption leaves without any file, whose successor is its legacy folder — are bent to
  the new place (the legacy copy, or the one successor an `adopt` row names), **the link target
  only**: the target of a Markdown link `](…)` or of a reference
  definition `[x]: path` (relative stays relative, the anchor stays). No other character, never
  inside a code block. **A path in backticks is text and is never changed**: it is listed as
  "mention in text — not changed", with both readings (relative to the file and to the root). A
  link with no successor or with several also stays and is listed. The full list, bent and left
  with the reason, goes to `<dir>/.act-local/adopt/references.txt` (`--finish --plan`:
  `references.plan.txt`); the terminal gets the counts. The orchestrator goes through every
  listed mention with the owner and changes the text only where the owner says so. The bent files
  are left unstaged (group 5 in step 8).

Then `doctor.py` runs and a report lands at `docs/ai/inbox/report-<timestamp>-adoption-report.md`. Its
accounting counts every `adopt` row `at target`, marked `into itself` where the target is its own
path.

Check the result against the project, not the checkout:

```bash
python .act/scripts/doctor.py --target <dir>
```

**By hand only what the report names.** `doctor` still reports every hook command and every
`Bash(...)` permission in `.claude/settings.json` (and, read-only, `.claude/settings.local.json`)
that names a script no longer in the project. After `--finish` those are only the entries under
that same heading ("Remove it by hand, or check" / German "Von Hand entfernen, oder prüfen"): the
orchestrator settles them with the owner
before committing and edits `settings.json` in place (it goes with group 2); `settings.local.json`
is the owner's to clean. A script that should have stayed needed `keep` in step 2 — after
`--finish` it is gone with its row. Afterwards `doctor.py --target <dir>` reports 0 findings.
