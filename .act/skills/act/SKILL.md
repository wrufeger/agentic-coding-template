---
name: act
description: List the project's skills with a one-line description from each one's frontmatter, like a man page; given a name, show that skill in full. Use when asked what skills or commands exist, or for one skill's exact instructions.
---

# List project skills

1. **No argument:** read `name` and `description` from every `SKILL.md` under `.agents/skills/*/`
   — the tool-neutral copy that already has any project override baked in, see
   `.act/skills/README.md` — and print them as a short table, sorted by name. Nothing else: no
   commentary, no summary, no skill started.
2. **With a name:** print that skill's `SKILL.md` in full and unchanged, in a code block. Name not
   found: say so and show the table from step 1 instead of guessing which one was meant.

## Gap in this stage

No script does this listing yet. Doing it by hand for a handful of skills is fine; once the count
of skills makes that slow or it gets repeated every session, this belongs in `.act/scripts/`
instead (`R-cost-script`), same as any other recurring, scriptable check.
