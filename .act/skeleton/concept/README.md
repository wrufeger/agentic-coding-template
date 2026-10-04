<!-- act:default -->
Everyone on the project has their own file here for ideas, wishes and concept notes:
`ideas-<identity>.md`, `<identity>` being the short name in `.act-local/identity.json` (the same one
`for:` and the board use). `init` creates it for the owner, the session start for everyone else the
first time they open a session in this project. It is versioned, and nobody but its owner writes
entries in it — so two people never edit the same file.

Write each idea as its own `## <title>` section. The next session start notices what is new or
changed since the assistant last went through your file and has it processed:

- **Only you write entries** and change the layout of your file. The assistant writes only answer
  blocks below an entry, never inside your text.
- **Answer block**, below a line at the end of the entry — only where something needs you (a
  question, a decision, a risk worth knowing):

  ```text
  ---
  YYYY-MM-DD HH:MM — HEADING
  TEXT (at most three lines)
  -> questions Q<n> · tasks T<n> · details <link>   (only what applies)
  ```

  The heading is **bold** while it is new or updated, and plain once you have edited the entry
  again — so you see at a glance what was added since you last read it. At most three blocks per
  entry; more points are bundled into one of them, never appended as a fourth.
- **Draft:** an entry with "Draft" in its heading — or the word for it in the language of these
  docs — gets only a short first reaction, no analysis: you are still thinking. Remove the word,
  and the entry is processed completely: feasibility, cost, time, risks, alternatives, benefit,
  follow-up ideas.
- **Decisions go to the inbox.** A decision only you can make becomes a question under
  `docs/ai/inbox/`; the answer block names its id.
- **Processed means moved.** An entry that needs nothing more from you and is no draft moves, with
  its full wording, into the backlog item or concept it became, and leaves this file. Nothing you
  wrote is shortened or reworded on the way.

Someone else's file is theirs: read it, write your own ideas into your own file.

## Starting text of a new file

A new `ideas-<identity>.md` starts with the block below; `{identity}` becomes the person's short
name. Change the block here to change it for everyone who joins later — existing files stay as
they are. Keep the mark line above the block and the `{identity}` placeholder as they are.

<!-- act:ideas-start -->
```markdown
# Ideas — {identity}

Your own ideas, wishes and concept notes for this project, one `## <title>` section each — only
you write entries here. The next session start picks up what is new or changed and answers below
the entry where something needs you. Rules: [README.md](README.md).

---
```
