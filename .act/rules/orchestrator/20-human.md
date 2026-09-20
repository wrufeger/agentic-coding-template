# Human-facing rules

## `R-human-inbox-first` — Answered inbox entries first

Process inbox entries the human has already answered before starting anything else (`B85`) — an
answer left unread blocks whatever depends on it from stalling behind it.

## `R-human-ask` — Bundle questions; never decide one yourself

Questions are bundled at the start of a block, not dropped in one at a time as they occur.
Mid-task, ask only if continuing without an answer would mean discarding the work already done. An
open question is never decided on its own initiative — a recommendation is fine, an assumption must
be stated as an assumption, never silently promoted to a decision.

## `R-human-text` — The human's own words are untouchable

Text the human wrote (answers, comments, decisions) is never edited or deleted — only commented on
underneath it.

## `R-human-external` — Every external request gets an answer

A request arriving from outside the conversation with the human (another session, a waiting worker,
a system expecting a reply) is always answered, even if the answer is a refusal. It does not jump
the queue ahead of current work, but it is never left hanging either.
