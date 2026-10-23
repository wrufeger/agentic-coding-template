---
name: act-version
description: Use when asked which template version is installed, which versions or releases the source offers, or what act-update would take ("act-version", "which ACT version", "is there a newer release"). Prints the answer from a script, writes nothing. Not for applying an update - use act-update.
---

# Show the template version

Run `python .act/scripts/update.py --versions` and pass its output on unchanged. The script reads only
`git ls-remote` (tags and the tip of the default branch), clones nothing and writes nothing.

It shows, in this order: the installed version and commit with the update channel (`update-channel` in
`docs/ai/config.md`, `release` by default), the source (a user name in a URL is masked), the releases
with `← installed` / `← newer` marks and the tags it does not offer, the tip of the default branch, and
`act-update would take: …`.

- `--all` lists every release, not the five newest. `--channel release|latest` shows the other channel for
  this run. `--source <path-or-url>` asks another source.
- A source without Git, or one that does not answer within a few seconds, gives the installed version and the
  reason — never a guess. An empty commit in `.act-lock.json` reads "commit unknown", never "up to date".
- If the answer is "a newer release is available" or "main differs", offer `act-update`; do not start it
  unasked.
