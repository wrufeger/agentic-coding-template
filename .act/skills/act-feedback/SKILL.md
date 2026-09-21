---
name: act-feedback
description: Send feedback to the template author about the working method itself - a rule, workflow, script, or skill that helped or was missing - never project specifics. Use when asked to send feedback, report something back to the template, or note a bug in the template.
---

# Send feedback to the template author

Reports a **pattern** in how this template's rules, roles, and skills served the work here — never
a project fact. The test for every entry: would this help someone who will never see this project?

## Two paths — do not conflate them

1. **A sentence right after the trigger** (`feedback: <text>`, "send feedback: <text>", "report to
   the template: <text>") **is the message itself.** It goes out exactly as written — no
   rewording, no addition — regardless of the feedback switch in `docs/ai/config.md`. With
   feedback off, only this text plus the template stamp (`.act-lock.json` § `template`
   `version`/`commit`) leaves the project, with no project identity attached.
2. **The trigger alone, nothing after it, means: assemble the collected feedback.** Go through
   `.act/`, the generated bridges, and `docs/ai/` and ask what would help someone who will never
   see this project: a rule added here because the template lacked it, a workflow that worked well
   or kept failing, a script or skill born here that generalizes, a useful link from
   `docs/ai/local/resources.md` if the project keeps one (never one from its "private links"
   section — that section exists precisely to stay out; **gap:** the skeleton ships no
   `resources.md`, so this source is optional, not guaranteed). One entry per finding, two to six
   sentences, pattern not case (see table). Whether this leaves the project on its own is the
   feedback switch's call, never overridden for a good finding.

## Immediate trigger: a bug in the template itself

A script or skill under `.act/` failing or doing the wrong thing, an update pulling in something
that should have stayed out (or skipping something it should have added), two of the template's
own rules contradicting each other, a rule that provably never fires — report this at once,
independent of any cadence setting: unreported, it keeps hitting every other project derived from
the template. Still the pattern, never the case; still gated by the feedback switch, never by a
cadence.

## What a good entry looks like

| Not this | But this |
| :--- | :--- |
| "`app/stores/countries.ts` was missing a return type" | "The TypeScript rule set had no rule for explicit return types" |
| "We switched the project to Kysely" | "A concept with options helped more than a task once, because the decision itself wasn't made yet" |
| "Our customer needs two databases" | "Two same-kind MCP servers with different credentials need separate config entries; nothing said so" |

## Limits

Nothing that only holds for this project — no project name, no paths, no numbers, no code, no
people. No praise ("works well" helps nobody) — only what concretely helped or was missing.

## Gap in this template stage

The send mechanism itself — a script, and the feedback on/off/cadence/scope switches in
`docs/ai/config.md` — doesn't exist yet at this build stage. Until it lands: write the entry down
in the inbox (`for: all`) instead, say plainly that sending still needs a human's hand, and leave
it there rather than guessing a switch that isn't built.
