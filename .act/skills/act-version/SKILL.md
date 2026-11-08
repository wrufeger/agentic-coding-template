---
name: act-version
description: Use when asked which template version is installed or which releases the source offers ("act-version", "is there a newer release"). Writes only the local update note. Not for applying an update - use act-update.
disable-model-invocation: true
---

# Show the template version

The session hook answers `/act-version [--all]` before the model sees it. If you see this anyway, run
`python .act/scripts/update.py --versions --short` (`--all` instead of `--short` for the full list) and show its
(at most three) lines unchanged. When the last line reads
`Update: … available`, offer `act-update`; on `Update: none, …` offer nothing. Do not start it unasked.
