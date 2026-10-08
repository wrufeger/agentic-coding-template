---
name: act-feedback
description: Use when asked to send feedback, "report to the template", or "feedback: <text>", or when a rule, workflow, script or skill of the template itself helped, failed or was missing, including a template bug. Sends a pattern about the working method to the template author, never project specifics.
---

# Send feedback to the template author

Reports a **pattern** in how this template's rules, roles, and skills served the work here — never
a project fact. The test for every entry: would this help someone who will never see this project?

Mechanism: `.act/scripts/feedback.py` (`--status`, `--enable`/`--disable`, `--add`, `--plan`,
`--send`, `--direct`, `--due`, `--postpone <days>`, `--clear`), privacy checks in
`.act/scripts/feedback_privacy.py`. Full policy, including the
`feedback`/`feedback-cadence`/`feedback-scope` keys and the immediate-trigger rule for a template
bug: `.act/rules/topics/feedback.md`.

## Two paths — do not conflate them

1. **A sentence right after the trigger** (`feedback: <text>`, "send feedback: <text>", "report to
   the template: <text>") **is the message itself.** Run `feedback.py --direct "<text>"` — it goes
   out exactly as written, no rewording, no addition — regardless of the feedback switch in
   `docs/ai/config.md`. With feedback off, only this text plus the template's own commit hash
   (`.act-lock.json` § `template.commit`) leaves the project, with no project identity attached.
2. **The trigger alone, nothing after it, means: assemble the collected feedback.** Go through
   `.act/`, the generated bridges, and `docs/ai/` and ask what would help someone who will never
   see this project: a rule added here because the template lacked it, a workflow that worked well
   or kept failing, a script or skill born here that generalizes, a useful link from
   `docs/ai/local/resources.md` if the project keeps one (never one from its "private links"
   section — that section exists precisely to stay out; **gap:** the skeleton ships no
   `resources.md`, so this source is optional, not guaranteed). One entry per finding, two to six
   sentences, pattern not case (see table) — `feedback.py --add --kind <kind> --title "..."
   --text "..."`. Preview with `--plan`, send with `--send` (mind the cadence gate; `--force`
   lifts it, never the consent gate). Whether this leaves the project on its own is the feedback
   switch's call, never overridden for a good finding — except a template bug, see below.

## Immediate trigger: a bug in the template itself

A script or skill under `.act/` failing or doing the wrong thing, an update pulling in something
that should have stayed out (or skipping something it should have added), two of the template's
own rules contradicting each other, a rule that provably never fires — report this at once,
independent of any cadence setting: unreported, it keeps hitting every other project derived from
the template. `feedback.py --add --kind bug --title "..." --text "..."` bypasses the cadence gate
by itself the moment the entry is stored. Still the pattern, never the case; still gated by the
feedback switch, never by a cadence.

## What a good entry looks like

| Not this | But this |
| :--- | :--- |
| "`app/stores/countries.ts` was missing a return type" | "The TypeScript rule set had no rule for explicit return types" |
| "We switched the project to Kysely" | "A concept with options helped more than a task once, because the decision itself wasn't made yet" |
| "Our customer needs two databases" | "Two same-kind MCP servers with different credentials need separate config entries; nothing said so" |

## Limits

Nothing that only holds for this project — no project name, no paths, no numbers, no code, no
people. No praise ("works well" helps nobody) — only what concretely helped or was missing.

## What scope `c` sends

Scope `c` (tool usage) sends the counts of agents/skills/scripts on disk and, since the last
sending, how often each of the template's own skills and scripts was used (from
`.act-local/usage.json`). The project's own skills and scripts appear only as one `own` counter
per kind, never by name, and no MCP server names are sent (see `feedback.py`'s own header comment
for the exact fields). `--plan` shows the payload without sending it.
