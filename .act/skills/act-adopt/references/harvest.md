# Handling the harvest (step 7)

Read from step 7 of `SKILL.md` when `--finish` names `harvest.md`.

**Ask consent for the harvest now, not before.** `--finish --plan` and `--finish`
both name `<dir>/.act-local/adopt/harvest.md` when step 6 found anything. Reading `feedback` from
`<dir>/docs/ai/config.md` decides what happens to it — every command below takes `--target <dir>`
so it acts on the adopted project, not on this checkout:

- `off`: nothing is asked, nothing is kept — `python .act/scripts/feedback.py --target
  <dir> --discard-harvest` removes the file; mention once, in the closing summary, that candidates
  for the template were found but discarded (feedback is off).
- `manual`: turn every harvest line into an entry (`python .act/scripts/feedback.py --target <dir>
  --add --kind <rule|script|skill|workflow|docs|bug|mcp|link> --title "<one line>" --text
  "<2-6 sentences>"`, one call per line) — they wait in the outbox, nothing is sent; the owner
  sends later via `/act-feedback`.
- `confirm`: same `--add` calls, then show the owner the assembled payload
  (`feedback.py --target <dir> --plan`) and ask yes/no; on yes, `feedback.py --target <dir> --send
  --yes`.
- `automatic`: same `--add` calls; each one sends on its own when `feedback-cadence` is
  `immediate` (`.act/rules/topics/feedback.md`), otherwise it waits in the outbox for the next
  scheduled send — no extra `--send` call needed here.

Once the harvest is handled (discarded, or every line turned into an entry), delete
`harvest.md` if it is still there (`--add` does not remove it): it has done its job and is not
itself part of the entry system.
