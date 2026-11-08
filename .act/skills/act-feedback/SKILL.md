---
name: act-feedback
description: 'Use when asked to send feedback, "report to the template", or "feedback: <text>", or when a rule, workflow, script or skill of the template itself helped, failed or was missing, including a template bug. Sends a pattern about the working method to the template author, never project specifics.'
---

# Send feedback to the template author

Reports a **pattern** in how this template's rules, roles, and skills served the work here — never
a project fact. The test for every entry: would this help someone who will never see this project?

Mechanism: `.act/scripts/feedback.py` (`--status`, `--enable`/`--disable`, `--add`, `--plan`,
`--send`, `--direct`, `--due`, `--postpone <days>`, `--clear`). The policy — the `feedback`,
`feedback-cadence` and `feedback-scope` keys, `feedback: local`, the immediate trigger for a template bug, what a
good entry looks like, the privacy check, where a send is recorded — stands in `.act/rules/topics/feedback.md`
and applies here unchanged.

## Two paths

1. **A sentence right after the trigger** (`feedback: <text>`) **is the message itself:**
   `feedback.py --direct "<text>"`, exactly as written, whatever the feedback switch says (except `local`, which
   sends nothing: a backlog entry per finding instead, `python .act/scripts/entries.py new backlog <title>`, the
   human's words unchanged). `--contact <email>` only when the human names a reply address in this request; do
   not ask for one.
2. **The trigger alone** means: assemble the collected feedback. Go through `.act/`, the generated bridges and
   `docs/ai/` for a rule added because the template lacked it, a workflow that worked or kept failing, a script
   or skill born here that generalizes, a useful link from `docs/ai/local/resources.md` if the project keeps one
   (never from its "private links" section; the skeleton ships no such file). One entry per finding, two to six
   sentences, pattern not case: `feedback.py --add --kind <kind> --title "..." --text "..."`. Preview with
   `--plan`, send with `--send` (`--force` lifts the cadence gate, never the consent gate). Whether this leaves
   the project is the feedback switch's call, never overridden for a good finding.

A bug in the template itself is reported at once (`--add --kind bug`), see `feedback.md` § "Immediate trigger".
A rule that keeps being violated is worth an entry too, as a candidate for a mechanical check.

## What scope `c` sends

Scope `c` (tool usage) sends the counts of agents/skills/scripts on disk and, since the last sending, how often
each of the template's own skills and scripts was used (from `.act-local/usage.json`). The project's own skills
and scripts appear only as one `own` counter per kind, never by name, and no MCP server names are sent.
`--plan` shows the payload without sending it.
