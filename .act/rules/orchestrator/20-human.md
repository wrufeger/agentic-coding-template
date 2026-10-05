# Human-facing rules

summary: inbox order, bundled questions, short final chat answers, chat language, untouchable human text, external requests

## `R-human-inbox-first` — Answered inbox entries first

summary: clearing answered inbox entries before other work

Process inbox entries the human has already answered before starting anything else — an
answer left unread blocks whatever depends on it from stalling behind it.

## `R-human-ask` — Bundle questions; never decide one yourself

summary: bundled questions upfront, stated assumptions, no silent decisions, inbox-decisions

Questions are bundled at the start of a block, not dropped in one at a time as they occur.
Mid-task, ask only if continuing without an answer would mean discarding the work already done. An
open question is never decided on its own initiative — a recommendation is fine, an assumption must
be stated as an assumption, never silently promoted to a decision.

Where an open decision waits follows `inbox-decisions` in `docs/ai/config.md`. With `immediate`
(the default), an open decision that arises while booking a finding, a backlog item or a task, and
every step only the human can take and can take now, goes into the inbox in the same step (question
or todo, `R-human-chat`), and the booked entry names its id — the inbox always shows everything
waiting. With `at-start`, a backlog entry may keep its open decisions, marked `decision: open` in
its header, and they are asked when work on it starts (`act-prepare`); a task's open decisions are
always in the inbox.

## `R-human-chat` — Answer once, briefly, when the answer is final

summary: no interim reports, questions in the inbox, short closing summary

Reply only when the answer is final — not while it still depends on running workers or pending
findings, and never with one worker's report while others are still running. On a long run a
one-line status is fine ("builder done, now review and tests"). A turn triggered only by a
worker's completion notice ends with no text at all, or at most one line — never a multi-sentence
status recap — except when that very notice makes the answer final: then the short closing summary
below follows. In chat, ask only the question work cannot continue without; every other question
goes to `docs/ai/inbox/` as `kind: question` (one file per question, `entries.py new question
<title>`) and is not repeated in chat — a decision question is created *only* as that inbox file,
chat names at most its id (e.g. "see Q<n>"), never restates the question itself. An inbox entry
the human has already answered is booked and archived in the same turn that notices the answer,
never left open. Close with a short summary — done · next · problems · to discuss — short, but
without dropping anything that matters, and name new questions and tasks together in one closing
line ("New questions: Q12–Q14, new task T7"). Details only on request.

## `R-human-language` — Talk in the owner's language

summary: chat in language-chat; with auto, detect once, remember per machine, reuse; no hint yet means language-docs

Talk to the owner in `language-chat` from `docs/ai/config.md`; a fixed value there always wins.
With `auto` (the default), use the language the session start names as remembered. If none is
remembered, recognize it once from the owner's own messages — not from quoted text, code or file
contents — and remember it with `python .act/scripts/board.py --chat-language <code>` (this person,
this machine, `.act-local/`, never versioned). Before there is anything to recognize, use
`language-docs`. When starting `init.py` for the owner, suggest their language as
`--language-docs <code>`. The chat language never changes what goes under `docs/`
(`R-work-language`).

## `R-human-text` — The human's own words are untouchable

summary: the human's own words left untouched, comments only beneath them

Text the human wrote (answers, comments, decisions) is never edited or deleted — only commented on
underneath it.

## `R-human-external` — Every external request gets an answer

summary: every outside request answered, even a refusal, without jumping the queue

A request arriving from outside the conversation with the human (another session, a waiting worker,
a system expecting a reply) is always answered, even if the answer is a refusal. It does not jump
the queue ahead of current work, but it is never left hanging either. A reply promised, or a
counter-check expected from another session, is filed as a todo (`entries.py new todo`) with `for:`
naming whom or what it waits for (or `all`), so the promise outlives the session.
