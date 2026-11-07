# Project docs order — details

summary: what `R-docs-order` asks for, what `act-doctor` reports, how to switch it, how to move a document

Detail page for `R-docs-order`. The rule keeps the requirement; the numbers, the check and the way to
move a document stand here.

## The layout

- `docs/README.md` lists the folders and the top-level files of `docs/` and nothing below them.
- Every folder under `docs/project/` with five or more entries (Markdown files and subfolders, not counting
  its `README.md`) has a `README.md`: its purpose, the format of its files and one line per file and
  subfolder with the state (open, decided, current, data as of a date). A smaller folder needs none; the
  `README.md` above it lists the folder, and `docs/project/README.md` is the top of that chain. A folder that has a `README.md` is held to it whatever its size.
- One topic per file. Past about 300 lines a file becomes a folder with a `README.md` and parts. A
  subfolder is for a series only, at most two levels below `docs/project/`.
- A number in a file name only for a series with a reading order, in a folder of its own; otherwise a
  speaking name.
- No archive folder under `docs/project/`. What is finished goes to `docs/ai/work/archive/` and, folded by
  `act-compact` into the monthly files, stays there; the journal under `docs/ai/work/` is the lasting record.
- A concept under `docs/project/concepts/` lives while it is open. Decided: the build goes into its backlog
  item or task, the reason into a decision record. Built: the result stands in the code, the journal, the
  project docs or a learning. Then the file is archived with `python .act/scripts/entries.py archive <file>`;
  `act-compact` folds it into the monthly file (`other-<YYYY-MM>.md`), and only then is it gone. A concept is
  never just deleted.

## What `doctor.py` reports

All four kinds are findings like any other (exit 1); none rewrites a file.

- `docs-index-missing` — a folder with five or more entries and no `README.md`, or a file or subfolder that
  its folder's `README.md` does not name. A name counts as named when it appears in the README outside a
  fenced code block, alone or as the end of a path or link; a folder counts only as `name/` or in backticks,
  not as a plain word. Only Markdown files and subfolders count; pasted images are reached through the
  document that shows them. Folders and files that Git ignores are skipped everywhere (without Git, none is).
- `docs-index-stale` — an index line (table row or list item) in a folder `README.md` whose first path (in
  backticks or as a link target, ending in `.md` or `/`) names nothing. Paths are read relative to the
  folder, or to the project root when they start with `docs/`.
- `docs-link-dead` — in `docs/README.md` and every Markdown file under `docs/project/`: a relative Markdown
  link or `<img src>` whose target does not exist, and a path in backticks that starts with `docs/project/`
  and ends in `.md` and does not exist (not checked in `decisions.md`: decision records name files that were
  deleted later). Code blocks are skipped; a link whose text holds code is still checked. Limits: a path broken over
  two lines, a path without a folder in front of it (a bare file name) and an anchor inside a file are not
  seen.
- `docs-concept-decided` — a file under `docs/project/concepts/` that names questions (as `Q<number>` in
  backticks; a bare quarter name in running text is not a question) when none of them is still open: each is answered or
  done (also in the archive or a monthly file), or its entry is gone and its number is reserved (left from the
  retired `done-entries: delete`). A concept
  that names no question is not reported, and neither is one that names an open one. The report is a
  prompt to apply the lifecycle above, not a judgement that the concept is finished.

## Switch

`docs-order` in `docs/ai/config.md` § Checks: `warn` (the default, also while the row is missing), `block`
(counts as `warn`, since the check only reports) or `off` (nothing is reported). A project that orders its
docs differently switches the check off, or replaces the rule in `docs/ai/rules.md`.

## Moving a document

Do not move a document by hand: links break where nobody looks.
`python .act/scripts/move_doc.py <from> <to>` shows what it would do;
`--apply` does it. It moves the file or folder (anything below `docs/`, `docs/ai/` excluded), rewrites the
relative links in every Markdown file under `docs/` and in the Markdown files at the project root, writes
the new path where the old one stood with its folder (`docs/project/old.md`) in the files under `docs/`, and
moves the index line to the `README.md` of the new folder, its links recomputed. The journal and the Markdown
files at the project root (`CHANGELOG.md`) keep old paths on purpose. A byte order mark and the line endings
stay; a file that is not UTF-8 is not touched and is listed when it names the file. What the script cannot know it
prints for a manual look: the bare file name mentioned somewhere, an index line it could not place. Stage
both the old and the new path; afterwards run `doctor.py`.
