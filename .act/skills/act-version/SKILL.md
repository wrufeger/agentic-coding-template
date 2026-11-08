---
name: act-version
description: Use when asked which template version is installed or which releases the source offers ("act-version", "is there a newer release"). Writes only the local update note. Not for applying an update - use act-update.
disable-model-invocation: true
---

# Show the template version

The session hook answers `/act-version [--all]` before the model sees it. If you see this anyway, run
`python .act/scripts/update.py --versions [--all]` and show its output unchanged. For "a newer release is
available" or "main differs", offer `act-update`; do not start it unasked.
