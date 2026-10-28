---
name: act-compact
description: Use when the session start says archive compaction is due, or when asked to compact or merge the archive or the journal. Merges old archived entries and journal entries word for word into one file per kind and month with a monthly overview, checks nothing was lost, and commits that run on its own. Never run by a sub-agent.
---

# Compact the archive and the journal

Keeps `docs/ai/work/archive/` and `docs/ai/work/ledger/` small: a thousand single files per folder are
unreadable in the IDE and cut off on the web. Applies `R-code-commit`. Every step is a script; no worker
takes part and no section is shortened.

## When

Controlled by `archive-compact: <days>d <files>` in `docs/ai/config.md` § Archive (default `30d 300`;
`off` disables). The session start names a due folder once a day, with the number of entries. Run this
skill at the next task boundary: no worker running, nothing open in chat, the working tree clean. In
`team` mode only on the default branch, so two branches never write the same month file; elsewhere say
so and stop.

## Steps

1. **Plan.** `python .act/scripts/entries.py compact --plan` lists what would be merged and writes
   nothing. Entries archived within the last 7 days, `archive/legacy/` and anything not committed stay
   as they are; commit pending archive changes first, the full text must be in Git.
2. **Merge.** `python .act/scripts/entries.py compact`. It writes
   `archive/<Q|T|B|U|other|ledger>-<YYYY-MM>.md`, one section per entry in full, names the commit that
   still holds the single files, and rewrites links. For every month with a Q, T, B or U section it
   writes the overview `archive/<YYYY-MM>.md`, one line per entry with a link to its section, or adds
   the missing lines to an existing one. Stage every path it prints.
3. **Check.** `python .act/scripts/compact_check.py` compares each section with its original from
   Git (ids, hashes, versions, dates, paths, numbers, the human's lines), the overview with the
   month's ids, and every single file the merge commit held against the sections (a deleted section
   is reported). Exit 1 lists what is missing; after a plain merge that points to a hand edit or a
   bug. `python .act/scripts/compact_check.py --restore` writes the full body of every flawed section
   back. Run it until it exits 0.
4. **Commit.** One commit for the whole run, by pathspec, nothing else in it: the collections, the
   overviews, the rewritten links, the removed single files, and a journal entry for the run
   (`act-commit` step 4). Message in the repo's style, naming the folder and the number of entries.

## Way back

`archive-compact: off` stops it. Reverting the run's commit restores every single file while no later
commit changed the month file; otherwise `git show <hash>:<folder>/<file>` returns one entry (the
hash is in the head of each collection, `<file>` in the second line of a section). The journal is
compacted the same way as the archive.
