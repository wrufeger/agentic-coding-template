---
name: act-pr
description: Use when asked to open a pull request, create a merge request, write a PR description, or "send this branch for review" on GitHub or GitLab. Drafts title and description from the branch diff, creates it only after a yes. Not for issues - use act-issue; not for local commits - use act-commit.
---

# Prepare and create a pull/merge request

Writes title and description from the branch's own commits and diff, shows them, and creates the
pull/merge request only after an explicit "yes". Approval, way back, journal, token and the write flow:
"Repo host and issue tracker" in `.act/rules/topics/live-systems.md` (`R-safe-approval`) — read it before the
first write. Runs in the main
session — it pushes and asks. **Difference:** `act-commit` only commits locally, `act-release` only tags; this
skill talks to the repo host. Only GitHub and GitLab (also self-hosted) work; Jira, YouTrack and Linear are not
supported yet.

1. **Access** — `python .act/scripts/integrations.py status`; exit 3: `act-integrations` first (it also sets
   `forge-host`, flow in `live-systems.md`).
2. **Target branch** — `python .act/scripts/forge.py target-branch` names the branch and its
   source. When the source is not `config target-branch`, ask the human to confirm the value and
   write it into `docs/ai/config.md` § `Git hosting` as `target-branch` (create the section if it
   is missing); from then on it is asked no more.
3. **Preconditions** — the current branch is not the target branch. Steps 1–2 may have written
   `docs/project/integrations.md`, `docs/ai/config.md` and a journal entry: commit exactly these
   files first, on their own, by pathspec (`act-commit`) — they are project files that stay
   whatever happens to the PR, so a separate commit is clearer than deferring the config value
   until after the PR exists (a failure in between would leave it unrecorded). Then `git status`
   must be clean (else stop, `act-commit` first).
4. **Pushed and current, no duplicate** — `git status -sb` shows the branch with an upstream and no
   `ahead` (`git rev-parse @{u}` equal to `git rev-parse HEAD` also does). Not pushed or ahead: ask
   "push `<branch>` to `<remote>`?" and push only after the human's own "yes" — only the
   orchestrator pushes, never a worker. Then `python .act/scripts/forge.py prs` (`--json` for the
   branches): when an open request for this branch exists already, show it and stop — no second one.
5. **Draft** — `git fetch <remote> <target>` first, so the comparison uses the remote's target
   branch, not a stale local one; then `git log <remote>/<target>..HEAD` and `git diff
   <remote>/<target>...HEAD`, written to a file under `.act-local/` (never into the repo):
   - **Title** in the commit message format of the project, one line: `docs/project/formats/commit.md`, else
     the preset `commit-format` names in `docs/ai/config.md` § Formats (`.act/formats/commit.md`); with the
     default `auto`, the style of the repo (look at `git log`).
   - **Description:** purpose (why), changes (what, grouped), evidence (tests run, with result),
     reference (`T<n>`; and, when the task file has a header field `issue: <URL>`, the issue —
     `Closes <URL>` only if the human wants it closed on merge).
6. **Preview** — `python .act/scripts/forge.py create-pr --source <branch> --target <target>
   --title "<title>" --body-file <file>` without `--apply` sends nothing and shows what would be
   sent. Show it to the human. Offer the choice: **create** · **create as draft** (`--draft`) · **only print
   the text** (nothing is sent) · **cancel**.
7. **Create** — after "yes" for exactly this preview: the same command plus `--apply`. Making a draft
   "ready for review" is its own "yes" (`live-systems.md`).
8. **Verify and record** — `forge.py prs` lists the new request with the right branches and title; show the
   link; journal entry (`R-work-record-now`). The way back is `forge.py close-pr <number>` (same flow).
