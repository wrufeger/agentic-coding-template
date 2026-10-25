---
name: act-compact
description: Use when the session start says archive compaction is due, or when asked to compact, merge or shorten the archive or the journal. Merges old archived entries and journal entries into one file per kind and month, has workers shorten them, checks nothing was lost, and commits that run on its own. Never run by a sub-agent.
---

# Compact the archive and the journal

Keeps `docs/ai/work/archive/` and `docs/ai/work/ledger/` small: a thousand single files per folder are
unreadable in the IDE and cut off on the web. Applies `R-cost-delegate`, `R-human-text` (its archive
exception) and `R-code-commit`.

## When

Controlled by two keys in `docs/ai/config.md` § Archive: `archive-compact: <days>d <files>` (default
`30d 300`; `off` disables) and `archive-shorten: on|off`. The session start names a due folder once a
day, with the number of entries and the worker runs to expect. Run this skill at the next task
boundary: no worker running, nothing open in chat, the working tree clean. In `team` mode only on the
default branch, so two branches never write the same month file; elsewhere say so and stop.

## Steps

1. **Plan.** `python .act/scripts/entries.py compact --plan` lists what would be merged and writes
   nothing. Entries archived within the last 7 days, `archive/legacy/` and anything not committed stay
   as they are; commit pending archive changes first, the full text must be in Git.
2. **Merge.** `python .act/scripts/entries.py compact`. It writes
   `archive/<Q|T|B|U|other|ledger>-<YYYY-MM>.md`, one section per entry, names the commit that still
   holds the single files, and rewrites links. Stage every path it prints.
3. **Shorten** (only with `archive-shorten: on`; with `off` go on at step 6). Cut the sections of each
   new or extended collection into batches of about 25 and start one `light` worker per batch, each
   with its own range of sections; workers on the same file run one after the other, workers on
   different files may run side by side with separate `Write scope:` lines. Each worker rewrites the
   body of its sections to about five lines: result or decision, the reason in a few words, references.
   Heading, anchor line and the header line under it stay. Kept verbatim: every id, hash, version,
   date, path and number, and every line the human wrote. Workers shorten only what is recognisably
   the assistant's: a paragraph that opens with a bold label (`**Context**`, `**Question:**`,
   `**Booked 2026-01-01:**`) and the option list directly below it. Every other non-empty line stays
   word for word, marked or not — an answer under "please answer here" has no marker, a bare "1a 2a"
   is an answer. Text below an empty answer label (`**Answer:**` or `**Antwort:**` alone on its
   line, the last line of every new question) is the human's, up to the next paragraph that opens
   with a bold label; so is the whole text of a `note` up to the assistant's first reply block, and
   of a `todo` captured from a chat prefix. A worker that is unsure leaves the section in full length.
4. **Overview.** For every month with a Q-, T-, B- or U- collection, write `archive/<YYYY-MM>.md`
   from the short sections (not the full texts): one line per topic, naming its ids —
   "`Q<n>`, `Q<m>`, `U<k>` — schema decided and built (`abc1234`)". Every id of the month must appear in it;
   an extended month gets its overview extended. The overview is plain Markdown without a header
   block and is never folded by `compact`.
5. **Check.** `python .act/scripts/compact_check.py` compares each section with its original from
   Git (ids, hashes, versions, dates, paths, numbers, the human's lines), the overview with the
   month's ids, and every single file the merge commit held against the sections (a deleted section
   is reported). Exit 1 lists what is missing. Either hand the section back to a worker with the list,
   or `python .act/scripts/compact_check.py --restore` writes the full body of every flawed section
   back. Run it until it exits 0.
6. **Commit.** One commit for the whole run, by pathspec, nothing else in it: the collections, the
   overviews, the rewritten links, the removed single files, and a journal entry for the run
   (`act-commit` step 4). Message in the repo's style, naming the folder and the number of entries.

## Way back

`archive-compact: off` stops it. Reverting the run's commit restores every single file while no later
commit changed the month file; otherwise `git show <hash>:<folder>/<file>` returns one entry (the
hash is in the head of each collection, `<file>` in the second line of a section). The journal is
compacted the same way as the archive.
