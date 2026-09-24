<!-- act:default -->
One question per file, `YYYY-MM-DD-<slug>.md`, created with `python .act/scripts/entries.py new
question <title>`. The header carries `for: all`, `status: open`, and `created: <timestamp>`
right away, and, once integrated, the assigned `id: Q<n>` (`docs/ai/config.md` § `mode`) — the
answer goes under the question in the same file, never above it (`R-human-text`), and `status`
flips to `answered` once it's there (the board keeps showing it, under "Answered"). Read by
`.act/scripts/board.py` for the board's questions lists. `created:` matters most before an id
exists: two branches filing the same title on the same day would otherwise merge into one file
silently — the timestamp keeps them apart.
