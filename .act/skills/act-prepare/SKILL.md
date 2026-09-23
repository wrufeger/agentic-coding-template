---
name: act-prepare
description: Prepare a larger block so it runs without interruptions - research what exists, cut it into tasks, check readiness, then ask everything open in one bundle. Use when planning a feature, asked to "plan this out", before a block that should run unattended, or when the human says they'll be away.
---

# Prepare a block

Runs in the main session — it ends with questions for the human. Applies `R-human-ask` (bundled
questions, stated assumptions) and `R-work-handover`. **In one sentence:** the human answers
everything open **once**, then the block runs unattended. The costliest mistake is a question the
code already answers, so research comes before the question round, never after.

1. **Bound the scope** — what's in, what's explicitly not, both written down.
2. **Research what exists, in parallel** — several `explorer` roles in one message: what already
   exists, which files are affected, does anything in `docs/project/decisions.md` conflict, where
   does the code differ from the docs.
3. **Cut it into tasks or stories.** Each task: one-sentence goal, checkable acceptance criterion,
   steps as bullets. Something bigger with its own justification becomes a story
   (`docs/project/stories/`, where the project uses them); the rest is a task under
   `docs/ai/work/tasks/` (`python .act/scripts/entries.py new task <title>`).
4. **Check readiness** — goal unambiguous, acceptance checkable, decisions made, preconditions
   met, unknowns researched. Anything failing this stays marked open and **doesn't start**.
5. **One bundled question round.** Numbered, answer options, a marked recommendation where there
   is one, ordered by how much each blocks, with one line on what happens if it stays unanswered.
   File the same questions under `docs/ai/questions/` (`entries.py new question <title>` per
   question) so the answer has somewhere to land — the board's Waiting section already surfaces
   them, no separate inbox entry needed.
6. **Record the answers**: ADR in `docs/project/decisions.md`, open points cleared, tasks marked
   ready. A question left open keeps its task on hold — never started "on best guess".
7. **Lay out the order**: what runs when and in parallel, checkpoints, rough duration — the plan
   the block runs on while the human is away.

## When the human is away

Explicitly cleared to run unattended ("I'll be away", "let it run through"):

- Work the prepared order — no new scope, nothing added along the way.
- Unexpected findings get noted and **skipped**, not waited on.
- Everything left is blocked: **stop**, don't build on a guess.
- Anything irreversible stays untouched even if it blocks the rest — being away is not approval
  (`R-safe-approval`).
- Journal and task status updated as they happen (`R-work-record-now`), not from memory later.
- On return: **one** summary — done with evidence, still open and why, the bundled questions.

## Limits

- No question research already answers; no code here — building happens afterward.
- No plan beyond the scope — something important found outside it becomes a backlog item, not an
  extra task in this block.
- Readiness isn't judged generously: "that'll sort itself out while building" is the sentence that
  causes the interruption later, or the stall with nobody there.
