# Handling the harvest (step 7)

Read from step 7 of `SKILL.md` when `--finish` names `<dir>/.act-local/adopt/harvest.md`. Ask consent now, not before.
`feedback` in `<dir>/docs/ai/config.md` decides; every command takes `--target <dir>`:

- `off`: nothing is kept: `feedback.py --target <dir> --discard-harvest`; mention once in the closing summary that
  candidates were found and discarded.
- `local`: each line becomes a backlog entry of the adopted project (`entries.py new backlog "<one line>"` run in
  `<dir>`, the 2-6 sentences as body), then `--discard-harvest`.
- `manual`: each line `feedback.py --target <dir> --add --kind <rule|script|skill|workflow|docs|bug|mcp> --title "<one line>" --text "<2-6 sentences>"`;
  they wait in the outbox, the owner sends later via `/act-feedback`.
- `confirm`: the same `--add` calls, show the payload (`feedback.py --target <dir> --plan`), on a yes `--send --yes`.
- `automatic`: the same `--add` calls; each sends on its own when `feedback-cadence` is `immediate`.

When done, delete `harvest.md` if still there.
