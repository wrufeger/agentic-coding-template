# Logging

Detail page for a rule that references it as `topics/logging.md`. Read this when
`docs/ai/config.md` § Logging has `logging` set to `on` — the session-start status line names
every topic whose switch is on, this one included, see `.act/hooks/checks/session.py`'s
`refresh_session()`. Mechanism: `.act/scripts/log.py`, observer `.act/hooks/checks/event_log.py`.

## What this is for

A live, line-per-event record of what the assistant did — not versioned, not a substitute for a
belief anyone should rely on later. Its only job is to be readable *while* work happens: a second
terminal during a talk, a human following along mid-task, a quick "what was builder#2 doing just
before it failed" a minute after the fact.

**Never a substitute for a belief anyone acts on.** "Done" still needs its own proof — a test run,
a commit hash, a call from outside that shows the result (`R-work-evidence`). A line in `ai.log`
is a recording, not a claim.

## Switches

Two keys in `docs/ai/config.md` § Logging:

- `logging`: `on` \| `off` (default). With `off`, `.act/hooks/checks/event_log.py` returns before
  opening any file — nothing is created the first time, and an existing `ai.log` is left exactly
  as it is. Turning it back on resumes appending to that same file, stale lines and all; a fresh
  file only ever comes from `--reset`.
- `log-level`: `DEBUG` \| `INFO` \| `WARN` \| `ERROR` (default `INFO`). Everything at or above the
  configured level is written; everything below it is silently skipped, not queued for later.
  `DEBUG` additionally writes one line per tool call (`[tool]`), which is loud enough to bury the
  decisions and delegations it sits between — turn it on only for a short diagnostic stretch.

## What gets written, automatically

Every hook event `.act/hooks/dispatch.py` sees also reaches `event_log.py` first (before any
PreToolUse check runs), which turns some of them into a line:

| Event | Line |
| :--- | :--- |
| `UserPromptSubmit` | `[user] [prompt]` — the prompt, masked and cut to 200 characters |
| `PreToolUse` for `Agent`/`Task`, orchestrator only | `[orchestrator] [delegate] <type> <- <assignment>` |
| `SubagentStart` | `[<type>#<n>] [start]` — `<n>` is the next free number for that type this session |
| `SubagentStop` | `[<type>#<n>] [end]` — only for a sub-agent this session actually started and numbered; the harness's own internal helper-agent stops (no matching `SubagentStart`, empty `agent_type`) never produce a line |
| `SessionStart` / `SessionEnd` | `[orchestrator] [session]` |
| `PostToolUseFailure` | `[<agent>] [error]` |
| `Notification` carrying a permission request | `[system] [session]` — "waiting for approval" |
| any other `PreToolUse`, `DEBUG` only | `[<agent>] [tool]` — tool name and a short argument |

A line the assistant writes **by hand**, `python .act/scripts/log.py <LEVEL> <agent> <topic>
"<text>"`, goes through the exact same `write_line()` — same masking, same 200-character cut, same
on/off and level gate.

## Duties once `logging` is `on`

- The orchestrator writes its own decision before a wave of delegation
  (`INFO orchestrator decision "..."`), the commit hash after a commit
  (`INFO orchestrator commit "<hash> <message>"`), and a one-line bilanz at the session's end
  (`INFO orchestrator session "ende · ..."`) — none of these three come from a hook, since no hook
  sees an orchestrator's own reasoning or a commit's message.
- A worker (sub-agent) writes at most 5 milestone lines under its own numbered label
  (`builder#2`), using `[test]`/`[result]`/`[review]`/`[docs]` as the topic — the exact rule and
  count live in the agent's own definition, this file only names the mechanism.
- No secret, ever — `log.py`'s own masking is the last line of defense, not the first one; do not
  rely on it to redact something typed on purpose.
- A line here is never cited as proof that something is done — see "What this is for" above.

## Reading it

```text
python .act/scripts/log.py --tail                       # last 20 lines, then follow
python .act/scripts/log.py --tail --grep builder         # one agent only
python .act/scripts/log.py --status                      # on/off, level, label counters
python .act/scripts/log.py --reset                       # ai.log -> ai.log.<timestamp>.bak
```

`ai.log` (and its `.bak` rotations) are gitignored — a talk's recording never lands in a commit by
accident.
