---
name: act-issue
description: Use when asked to "show issues", "show my open stories", "show issue 42", to create, comment on or close a GitHub or GitLab issue, or to "start work on issue 42". Covers issues and stories on the repo host. Not for pull or merge requests - use act-pr.
---

# Issues and stories

Sentences instead of subcommands, in three parts. Runs in the main session. Only GitHub and GitLab
(also self-hosted) work; Jira, YouTrack and Linear are not supported yet (trackers without Git). Before the first
call: `python .act/scripts/integrations.py status` — exit 3 means `act-integrations` first (also for
`forge-host`; flow in `live-systems.md`). Everything that writes follows `R-safe-approval` and the
rule section "Repo host and issue tracker" in `.act/rules/topics/live-systems.md` (approval, way back, journal,
token) — read that section before the first write.

## 1. Read — free, no approval

"show issues", "my open stories", "show issue 42":

- `python .act/scripts/forge.py issues [--state open|closed|all] [--mine] [--label <name>]
  [--limit <n>]` — show a table of at most 15 rows (number, title, labels, assignee); more rows
  are offered, not dumped.
- `python .act/scripts/forge.py issue <number>` — title, state, labels, text.
- `forge.py prs` lists pull/merge requests the same way.

## 2. Create, comment, close — only after "yes"

Each write: preview without `--apply`, show it, "yes" for exactly that preview, the same command plus
`--apply`, verify, journal (flow in `live-systems.md`). Draft: a title; a body with what, why, how to check. Commands:
`forge.py create-issue --title "<title>" --body-file <file> [--label <name>]`, `forge.py comment <number>
--body-file <file>`, `forge.py close-issue <number>`. Verify with `forge.py issue <number>`. The way back is
`close-issue`; for a comment a correcting comment, not closing.

## 3. Start work — "start work on issue 42"

1. `forge.py issue 42` — read it; summarize it in a few lines and name what is unclear.
2. `python .act/scripts/forge.py target-branch`, then `git fetch <remote> <target>` and the branch
   name from `forge.py branch-name 42` (`feature|bugfix/<number>-<short-title>`). Create it
   **locally** from the remote's target branch (`git switch -c <name> --no-track <remote>/<target>`,
   tree clean first); no push.
3. Show the summary and the working assignment (goal, scope, acceptance) and wait for the human's
   OK.
4. Then the flow of `act-prepare`: what exists already, cut into tasks (`entries.py new task
   <title>`), each task gets the header field `issue: <URL>`; everything open goes into **one**
   question block; tasks for the developer only once they are executable.
5. Bring backlog and docs up to date (`docs/ai/work/backlog/`, `docs/project/`).
6. Close with the hint: when the work is done, `act-pr` creates the pull/merge request (it reads
   `issue:` from the task and links the issue).
