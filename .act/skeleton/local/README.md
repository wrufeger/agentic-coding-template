The project's own or overriding files, mirrored after `.act/` — same relative path, same name
wins over the template version (`docs/ai/local/<path>` is looked up before `.act/<path>`). The
user owns this folder; the assistant writes here only on explicit instruction.

## `reminders.md` (optional)

Your own "remind me to ..." lines, one per line, shown in the same SessionStart slot as
`.act/tips.md`'s vendor tips — and ahead of them (`tips: never` in `config.md` only turns the
vendor tips off, never this file). Format:

```text
- <text>                no cadence — daily by default, once per session under `tips: regularly`;
                        `tips: never` only turns off the vendor tips, not this line
- session: <text>       once per session
- daily: <text>         at most once a calendar day
- weekly: <text>        at most once every 7 days
- once: <text>          shown exactly once, ever, then silent until you change the line
- every 90m: <text>     inside a running session, at least 90 minutes since last shown
- every 2h: <text>      same, in hours — minute/hour cadences cap at 3 lines per session
- every 3d: <text>      at least 3 days since last shown, checked at session start
- every 2w: <text>      at least 2 weeks since last shown, checked at session start
```

Not project-specific — "every 90m: take a break" is as valid as "weekly: run act-deps". Delete
the line when a reminder no longer applies; nothing else tracks that for you.
