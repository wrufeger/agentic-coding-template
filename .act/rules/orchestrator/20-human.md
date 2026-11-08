# Human-facing rules

summary: inbox order, questions, chat answers and language, human text, external requests

## `R-human-inbox-first` — Answered inbox entries first

summary: clearing answered inbox entries before other work

Process inbox entries the human has already answered before starting anything else. An entry
marked `triage: open` comes right after them (`R-human-capture`).

## `R-human-ask` — Bundle questions; never decide one yourself

summary: the one place for questions: bundled, chat only when work would be lost, else an inbox entry; no silent decisions

Questions are bundled at the start of a block, not dropped in one at a time. Mid-task, ask
in chat only if continuing without an answer would mean discarding the work already done. Every
other question is an inbox entry (`entries.py new question <title>`, in the form of
`docs/ai/inbox/README.md`), not repeated in chat, which names at most its id ("see
Q<n>"). An open question is never decided on the assistant's own initiative: a recommendation is
fine, an assumption is stated as one and never silently promoted to a decision; a default the tool or
the assistant states is an assumption too, and the project's rule wins over the tool's habit of
picking a sensible default. A decision the human makes in chat goes into the inbox at once, answered.

Where an open decision waits follows `inbox-decisions` (`docs/ai/config.md`): with `immediate` (the
default) it goes into the inbox in the same step as booking the finding, backlog item or task, together with every step only the
human can take now (question or todo), and the booked entry names its id; a task's open decisions are
always there.

## `R-human-capture` — Chat prefixes `todo:`, `note:`, `idea:` capture

summary: todo:/note:/idea: becomes an inbox entry or ideas section (hook, else entries.py new --triage); triage: open handled next

A chat message that begins with `todo:`, `note:` or `idea:` (any letter case) is a capture, not an
assignment. With `quick-capture` on (the default) the `UserPromptSubmit` hook files it and the message
never reaches the model. Where the hook does not run and such a message arrives anyway, file it
yourself at once, without starting on the todo: `todo:` and `note:` with `entries.py new todo|note
--triage --for <writer> [--body-file <file>] <title>` (first line of the wording as title, all of it
as body), `idea:` as a new section at the end of the writer's `docs/ai/concept/ideas-<identity>.md`,
text untouched. Answer with one line naming the file. With `quick-capture` off, the prefixes mean
nothing special.

Entries with `triage: open` are yours, whatever their kind: handle them right after the answered
inbox entries. A `todo` gets its `for:` decided or becomes a backlog entry that keeps the wording
(inbox file archived); a `note` gets a reply below it in the block form of the inbox README, the
human's text never edited, and `status: answered`. Finally the `triage:` line comes out.

## `R-human-chat` — Answer once, briefly, when the answer is final

summary: no interim reports, short closing summary, terse style, output-depth levels

Reply only when the answer is final — not while it still depends on running workers or pending
findings, and never with one worker's report while others are still running. On a long run a one-line
status is fine. A turn triggered only by a worker's completion
notice ends with no text, or at most one line, unless that very notice makes the answer final.
Questions follow `R-human-ask`. An inbox entry the human has already answered is booked and archived
in the same turn that notices the answer (`entries.py archive <id>`), never left open. Close with a
short summary — done · next · problems · to discuss — without dropping anything that matters, and
name new questions and tasks in one closing line ("New questions: Q12–Q14, new task T7"). Details
only on request.

Every answer is read again in each later step, so chat text is compact: answer first, three bullets
rather than three paragraphs. Numbers, negations, paths, identifiers, code and error text stay
verbatim; a warning, an irreversible or outward-facing step, and a question or decision put to the
human are written in full sentences. `output-depth` (`docs/ai/config.md`): `normal` (default, also for
an unknown value) is the above; `sparse` gives only what is needed, no interim status line, one answer
per question; `verbose` writes answers out in full, overriding "briefly" and "details only on
request": the question as understood, the reasons, and for code it wrote why and what to watch for.
Verbatim and full-sentence cases hold at every level; `docs/` text keeps its full form.

## `R-human-language` — Talk in the owner's language

summary: chat in language-chat; with auto, detect once, remember per machine, reuse; no hint yet means language-docs

Talk to the owner in `language-chat` (`docs/ai/config.md`); a fixed value always wins, also over the
tool's own language setting. With `auto` (the default), use the language the session start names as
remembered, else the tool's own; if neither is there, recognize it once from the owner's own messages
(not quoted text, code or file contents) and remember it with `python .act/scripts/board.py
--chat-language <code>` (per machine). Before there is anything to recognize, use
`language-docs`.

## `R-human-text` — The human's own words are untouchable

summary: the human's own words left untouched, comments only beneath them

Text the human wrote (answers, comments, decisions) is never edited or deleted — only commented on
underneath it.

## `R-human-external` — Every external request gets an answer

summary: every outside request answered, even a refusal, without jumping the queue

A request from outside the conversation with the human (another session, a waiting worker, a system
expecting a reply) is always answered, even if the answer is a refusal. It does not jump the queue
ahead of current work, but is never left hanging. A reply promised, or a counter-check expected from
another session, is filed as a todo (`entries.py new todo`) with `for:` naming whom or what it waits
for (or `all`), so the promise outlives the session.
