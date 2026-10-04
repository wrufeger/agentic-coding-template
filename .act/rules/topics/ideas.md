# Ideas

Detail page announced by the session-start topic line. "ideas" is active when the session owner's
own ideas file — `docs/ai/concept/ideas-<identity>.md`, rules for the human in that folder's
`README.md` — has entries that are new or changed since they were last processed; the session
start names them in an `[act] ideas:` note. Mechanism: `.act/scripts/ideas.py`, called from
`.act/hooks/checks/session.py`.

## When

After the answered inbox entries (`R-human-inbox-first`), before new work of your own — unless the
human has just asked for something else; then right after that. Only the owner's own file: another
person's ideas file is processed by their own session, never by yours — read it, never write it.

## Per entry the note names

1. **Read the entry whole**, earlier answer blocks included. A change that alters nothing of
   substance (a typo, a reworded sentence) needs no new block — at most turn your bold block
   headings plain (below).
2. **Draft** — "Draft" in the heading, or the word for it in `language-docs`: one short first
   reaction as an answer block, no analysis, nothing filed.
3. **Otherwise process it as an idea** per `act-idea`: check what exists, options, recommendation;
   analysis covers feasibility, cost, time, risks, alternatives, benefit, follow-up ideas. A
   decision only the human can make goes to the inbox as a question (`R-human-ask`), never decided
   here.
4. **Answer block** only where something needs the human; form and limits as in the folder's
   `README.md`: below a `---` line, date and heading, at most three lines of text, a closing line
   naming the inbox questions, tasks and pages it refers to; at most three blocks per entry. Your
   block heading is bold while new or updated; once the human has edited the entry since, turn the
   headings of your earlier blocks there plain.
5. **Done with an entry** — nothing more needed from the human, no draft: move its full wording
   verbatim (a quote block, with its date and source file) into the backlog item or concept page
   it became, then remove the section from the ideas file. The human's own text is never shortened
   or reworded on the way (`R-human-text`) — moving it whole, as the folder's own rules say, is not
   editing it.
6. **Write as little as possible** into the human's file, and re-read it right before every write:
   they may have it open in an editor, and a buffer saved later silently undoes your change.

## Close

Once the file is as you leave it, run `python .act/scripts/ideas.py --check` once more: an entry
it names that you have not handled was written while you worked — handle it first. Then
`python .act/scripts/ideas.py --seen`: it records the current state of every entry and names the
ones it marks as processed, so the next session start reports only what the human changes after
this. What was filed (backlog item, question, concept page) gets its journal entry as usual.
