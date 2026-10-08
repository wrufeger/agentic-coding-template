# After the run (step 4)

Read from step 4 of `SKILL.md` when an inbox note offers `security-check: deps`.

One of the notes from step 4 may offer `security-check: deps` (only when
`init` found a tool installed that Art B — the dependency-vulnerability scan,
`.act/scripts/security_scan.py` — could use, and only while `security-check` is still `local`, the
default): ask the owner whether to turn it on, and only if they say yes, set it to `deps` in
`docs/ai/config.md` yourself — `init` never switches it there on its own.
