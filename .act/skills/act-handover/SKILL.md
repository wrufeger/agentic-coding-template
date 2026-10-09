---
name: act-handover
description: Use when the human wants to hand over or leave the session - "hand over", "can I close the session", "is it safe to /clear", "new session". Checks that nothing is lost, fixes what it can, and ends with the sentence to type into the new session. Never clears on its own.
---

# Hand over the session

Answers "can this session be left now?" and makes it true where it can, so the human can `/clear` or
start a new session at any task boundary. Applies `R-work-handover`, `R-human-external`,
`R-human-ask` and `R-human-inbox-first`.

## Steps

1. **Run the check.** `python .act/scripts/handover.py` - uncommitted changes, started tasks without
   a state line, answered inbox entries, and the started tasks with their last state line.
2. **Running workers.** Any worker this session started without its completion notice yet means not
   ready: name it. No script knows them; the assistant knows its own workers.
3. **Anything only in chat.** A promise or an expected reply without a todo: `entries.py new todo`
   with `for:` (`R-human-external`). An open decision: into the inbox (`R-human-ask`). A finished,
   accepted but uncommitted change: `act-commit` (this skill never commits).
4. **Task state.** A started task without a state line, or whose state is older than what was done
   since: `python .act/scripts/entries.py state <id> <text>` with status and next step
   (`R-work-handover`).
5. **Answered inbox entries.** Book them first (`R-human-inbox-first`).
6. **Close.** Run the check again. Ready: give the one sentence for the new session in the chat
   language, e.g. "continue with T<n> - <next step>", and say "now `/clear` or a new session". Not
   ready: the short list of what still blocks it.

## Limits

- Never clears or ends the session itself; that stays with the human.
- Read-only on its own; every write goes through the scripts and skills named above.
