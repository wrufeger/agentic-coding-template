---
name: act-pr
description: Use when asked to open a pull request, create a merge request, write a PR description, or "send this branch for review" on GitHub or GitLab. Drafts title and description from the branch diff, creates it only after a yes. Not for issues - use act-issue; not for local commits - use act-commit.
---

# Prepare and create a pull/merge request

Writes title and description from the branch's own commits and diff, shows them, and creates the
pull/merge request only after an explicit "yes" (`R-safe-approval`; rule section
"Repo host and issue tracker" in `.act/rules/topics/live-systems.md`). Runs in the main session —
it pushes and asks. **Difference:** `act-commit` only commits locally, `act-release` only tags; this skill is the
one that talks to the repo host. Only GitHub and GitLab (also self-hosted) work; Jira, YouTrack
and Linear are not supported yet (trackers without Git). Never print or ask for a token in chat — it
comes from the environment or `.env` (`R-safe-no-secret-cli`).

1. **Access** — `python .act/scripts/integrations.py status`. Exit 3 (missing or stale): run
   `act-integrations` first, then continue.
2. **Target branch** — `python .act/scripts/forge.py target-branch` names the branch and its
   source. When the source is not `config target-branch`, ask the human to confirm the value and
   write it into `docs/ai/config.md` § `Git hosting` as `target-branch` (create the section if it
   is missing); from then on it is asked no more.
3. **Preconditions** — the current branch is not the target branch. Steps 1–2 may have written
   `docs/project/integrations.md`, `docs/ai/config.md` and a journal entry: commit exactly these
   files first, on their own, by pathspec (`act-commit`) — they are project files that stay
   whatever happens to the PR, so a separate commit is clearer than deferring the config value
   until after the PR exists (a failure in between would leave it unrecorded). Then `git status`
   must be clean (else stop, `act-commit` first). If `forge.py` stops with the hint to set
   `forge-host`, run `act-integrations` (the human confirms the host, then it is entered).
4. **Pushed and current, no duplicate** — `git status -sb` shows the branch with an upstream and no
   `ahead` (`git rev-parse @{u}` equal to `git rev-parse HEAD` also does). Not pushed or ahead: ask
   "push `<branch>` to `<remote>`?" and push only after the human's own "yes" — only the
   orchestrator pushes, never a worker. Then `python .act/scripts/forge.py prs` (`--json` for the
   branches): when an open request for this branch exists already, show it and stop — no second one.
5. **Draft** — `git fetch <remote> <target>` first, so the comparison uses the remote's target
   branch, not a stale local one; then `git log <remote>/<target>..HEAD` and `git diff
   <remote>/<target>...HEAD`, written to a file under `.act-local/` (never into the repo):
   - **Title** in the commit style of the repo (look at `git log`), one line.
   - **Description:** purpose (why), changes (what, grouped), evidence (tests run, with result),
     reference (`T<n>`; and, when the task file has a header field `issue: <URL>`, the issue —
     `Closes <URL>` only if the human wants it closed on merge).
6. **Preview** — `python .act/scripts/forge.py create-pr --source <branch> --target <target>
   --title "<title>" --body-file <file>` without `--apply` sends nothing and shows what would be
   sent. Show it and offer the choice: **create** · **create as draft** (`--draft`) · **only print
   the text** (nothing is sent) · **cancel**.
7. **Create** — only after "yes" for exactly this preview: the same command plus `--apply`.
   `forge.py` cannot mark a draft "ready for review": that is the human in the web interface, or
   the orchestrator after its own separate "yes".
8. **Verify independently** — `python .act/scripts/forge.py prs` must list the new request with
   the right branches and title (`R-work-evidence`); show the link.
9. **Record** the link, the date and the "yes" given in the chat (date, what was approved) in the
   journal (`entries.py`, `R-work-record-now`). No backup is needed — nothing is overwritten. The
   way back is closing (`forge.py close-pr <number>`, again preview, "yes", `--apply`), never
   deleting.

A failure of `forge.py` (exit 2, one line) is reported as it is; a wrong hoster guess is fixed
with `forge` in `docs/ai/config.md` § `Git hosting`; a self-hosted host refused a token needs
`forge-host` there (`act-integrations`). A bug in the script itself goes to
`feedback.py --add --kind bug`.
