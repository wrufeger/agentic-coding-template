# Whiteboard

Detail page announced by the session-start topic line. "whiteboard" is active when the session owner's own
whiteboard — `docs/ai/whiteboard-<identity>.md`, rules for the human in `docs/ai/README.md` — has entries that
are new or changed since they were last processed, a reminder on a date that is due, or a reminder on an event
to check; the session start names them in `[act] whiteboard:` notes. Mechanism: `.act/scripts/whiteboard.py`,
called from `.act/hooks/checks/session_context.py`.

`<identity>` is the short name in `.act-local/identity.json` (gitignored). The session start creates
that file from `git config user.name` when a checkout lacks it (fresh clone, second machine) and says
so in an `[act] identity` line — also when `session-start-refresh` is `warn` or `off`, the one thing it writes then; a file that exists but is unreadable is never overwritten, the session start only says so; without a usable git name it says that none exists — ask the human for
their name and run `python .act/scripts/board.py --identity <name>`, which also renames the whiteboard of the
former identity.

## When

After the answered inbox entries (`R-human-inbox-first`), before new work of your own — unless the
human has just asked for something else; then right after that. Only the owner's own file: another
person's whiteboard is processed by their own session, never by yours — read it, never write it.

## The kind of an entry

The heading says it: `## <kind>: <title>`, in any letter case, English or German; no kind means idea.

| Heading | Note | What you do |
| :--- | :--- | :--- |
| `Idea:` or none | `new or changed` | process it as an idea (below) |
| `Bug:` | `new or changed` | process it as a bug report: `act-bug`; a fault of the template itself goes to feedback, `R-work-override` |
| `Note:` | never named | nothing: never read into a task, never moved, never answered |
| `Reminder <YYYY-MM-DD>:` | `due` | from that day on: make it what it asks for (below) |
| `Reminder after <event>:` | `to check` | check whether the event has come (a release, a merge, an answer); not yet: leave the entry; come: as a due reminder |

A reminder whose date is not `YYYY-MM-DD` counts as a reminder on an event, so it is named every time.

## Per entry the note names

1. **Read the entry whole**, earlier answer blocks included. A change that alters nothing of
   substance (a typo, a reworded sentence) needs no new block — at most turn your bold block
   headings plain (below).
2. **Draft** — "Draft" in the heading, or the word for it in `language-docs`: one short first
   reaction as an answer block, no analysis, nothing filed.
3. **An idea or bug** — process it per `act-idea` or `act-bug`: check what exists, options, recommendation;
   analysis covers feasibility, cost, time, risks, alternatives, benefit, follow-up ideas. A
   decision only the human can make goes to the inbox as a question (`R-human-ask`), never decided
   here. A proposal for a rule, a setting or a checklist is such a decision: one inbox question for the
   project's owner, with the old text quoted and the target named.
4. **A due reminder, or one whose event has come** — file what it asks for: a todo for the human
   (`entries.py new todo --for <identity>`), a backlog item or a task when the work is yours; the
   reminder's wording goes in whole, as a quote.
5. **Answer block** only where something needs the human; form and limits as in `docs/ai/README.md`:
   below a `---` line, date and heading, at most three lines of text, a closing line
   naming the inbox questions, tasks and pages it refers to; at most three blocks per entry. Your
   block heading is bold while new or updated; once the human has edited the entry since, turn the
   headings of your earlier blocks there plain.
6. **Done with an entry** — nothing more needed from the human, no draft: move its full wording
   verbatim (a quote block, with its date and source file) into the backlog item, question, todo, task
   or concept page it became, then remove the section from the whiteboard. The human's own text is never
   shortened or reworded on the way (`R-human-text`) — moving it whole, as the whiteboard's own rules say, is
   not editing it. A note, and an event reminder whose event has not come, stay.
7. **Write as little as possible** into the human's file, and re-read it right before every write:
   they may have it open in an editor, and a buffer saved later silently undoes your change.

## Close

Once the file is as you leave it, run `python .act/scripts/whiteboard.py --check` once more: an entry
it names as new, changed or due that you have not handled was written while you worked — handle it first;
event reminders still to check may remain. Then `python .act/scripts/whiteboard.py --seen`: it records the
current state of every entry and the day, and names the ones it marks as processed, so the next session start
reports only what the human changes after this, and a due reminder stays quiet until its entry changes.
What was filed (backlog item, question, todo, task, concept page) gets its journal entry as usual.
