<!-- act:default -->
# docs/ai — the assistant's working area

Configuration, inbox, tasks, backlog and journal of the AI-assisted work on this project; `docs/README.md` names
every folder and top-level file. This page holds the rules for the whiteboards.

## Whiteboards

Everyone on the project has their own whiteboard here: `whiteboard-<identity>.md`, `<identity>` being the short
name in `.act-local/identity.json` (the same one `for:` and the board use). `init` creates it for the owner, the
session start for everyone else the first time they open a session in this project. If `.act-local/identity.json`
is missing (a fresh clone, a second machine), the session start creates it from `git config user.name`; change the
name with `python .act/scripts/board.py --identity <your-name>`. It is versioned, and nobody but its owner writes entries
in it — so two people never edit the same file. Anything meant for nobody else, not even the repository, goes under
`.act-local/` instead, which is not versioned.

Write each entry as its own `## <title>` section, the kind in front of the title, followed by a colon:

| Heading | Kind | What the assistant does |
| :--- | :--- | :--- |
| `## Idea: …`, or no kind | idea, wish, concept note | processes it at the next session start that finds it new or changed |
| `## Bug: …` | something that does not work | the same, as a bug report |
| `## Note: …` | a note for yourself | nothing: a note is never processed and never moved |
| `## Reminder 2026-12-01: …` | a reminder on a date (`YYYY-MM-DD`) | nothing before that day; from then on it names it until it is handled |
| `## Reminder after <event>: …` | a reminder on an event | names it at every session start, to check whether the event has come |

The kind words are read in any letter case, in English or German (`Idee`, `Bug`, `Notiz`, `Erinnerung 2026-12-01`,
`Erinnerung nach <Ereignis>`). A date that is not `YYYY-MM-DD` (`2026-13-01`, `01.12.2026`) makes the entry a
reminder on an event, so it is never lost.

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
  its full wording, into what it became — the backlog item or concept of an idea or bug, the todo or
  task of a reminder once it is due — and leaves this file. A note stays. Nothing you wrote is
  shortened or reworded on the way. Images linked from the entry go along, with the topic in front of
  a generic name like `img.png` and the link adjusted; `doctor` reports an image beside the
  whiteboards that no Markdown file under `docs/` links.
- **A proposal** for a rule, a setting or a checklist goes into your own whiteboard too; your session
  turns it into a question for the project's owner.

A chat message you send that begins with `idea:` is your own text too: the hook only copies it, unchanged, as a
new `## <title>` section at the end of your whiteboard.

Someone else's whiteboard is theirs: read it, write your own entries into your own.

## Starting text of a new whiteboard

A new `whiteboard-<identity>.md` starts with the block below; `{identity}` becomes the person's short
name. Change the block here to change it for everyone who joins later — existing files stay as
they are. Keep the mark line above the block and the `{identity}` placeholder as they are.

<!-- act:whiteboard-start -->
```markdown
# Whiteboard — {identity}

Your own ideas, bugs, notes and reminders for this project, one `## <kind>: <title>` section each —
only you write entries here. The next session start picks up what is new, changed or due and answers
below the entry where something needs you; a `## Note:` stays as it is. Anything private goes under
`.act-local/` instead. Rules: [README.md](README.md).

---
```
