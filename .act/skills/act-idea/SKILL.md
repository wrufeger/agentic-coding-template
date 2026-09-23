---
name: act-idea
description: Take in an idea, feature, or change request - check what exists, lay out options with a recommendation, get a decision, then estimate effort and missing tooling and file it as a backlog item and task. Use when a feature or change is proposed, or asked "can we add X", "it would be good if", "change request".
---

# Take in an idea or change request

Runs in the main session — decision and priority are the human's. Applies `R-work-idea-first`
(concept before code) and `R-human-ask` (bundled questions, no silent decisions). **Builds
nothing**: ends with a backlog item and, if picked up now, a task; building happens afterward via
`act-prepare`.

1. **Keep the wording verbatim** — the later yardstick, not the assistant's summary of it.
2. **Check what exists first** (`explorer` role): does this partly exist already, which files
   would be affected, and — above all — does it conflict with a decision in
   `docs/project/decisions.md`? A conflict makes this an ADR revision, not a feature.
3. **Write a concept** at `docs/project/concepts/<topic>.md`: starting point with findings,
   **options** (description, pros, cons, effort each), **recommendation**. "Do nothing" is a real
   option, with its consequences.
4. **Put it to the human** as a question under `docs/ai/questions/` (`python
   .act/scripts/entries.py new question <title>` — writes `for: all` into the header, `Q63b`),
   options labeled, recommendation marked. Nothing built, no task filed, before it's answered.
5. **Estimate for the chosen path only**: scope, missing tooling (library, MCP server, rule set,
   a skill that doesn't exist yet — its own step, not "along the way"), a rough task breakdown
   with goal and acceptance check, and an ADR in `docs/project/decisions.md`.
6. **Priority and timing**, both from the human — plus the orchestrator's **own** estimate next
   to it, from a different angle (pressure, dependencies, risk already in the codebase), not the
   same number out of politeness. More than one step apart: say where the gap comes from.
7. **File it** (`python .act/scripts/entries.py new <kind> <title>` for each): a backlog item
   under `docs/ai/work/backlog/` (topic, priority, timing, effort, link to concept and ADR); a
   task under `docs/ai/work/tasks/` only for what starts **now**; a journal entry under
   `docs/ai/work/ledger/`.

**Shortcut for small things:** a typo, a field name, one config line needs no concept or ADR —
file it straight, but say the shortcut out loud so the human can object. When in doubt, don't
shortcut: a needless concept costs half an hour, a missed conflict costs a rebuild.

## Limits

- No implementation here, not even "just a quick start" — that preempts the decision.
- No recommendation without a real alternative, and no quietly aligned priorities — the gap
  between the two numbers is itself information.
- No effort estimate without a stated assumption behind it.
