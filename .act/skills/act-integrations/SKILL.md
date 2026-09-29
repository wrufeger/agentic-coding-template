---
name: act-integrations
description: Check which ways lead from this project to its repo host and issue tracker (REST token, MCP servers), what each can do, and record it in docs/project/integrations.md. Read-only probes, never a write. Also proposes MCP servers from the catalog (.act/mcp-catalog.md) when asked, e.g. "which MCP servers fit?", and sets one up only after a yes. Use when asked what GitHub/GitLab access exists, before act-pr or act-issue when the file is missing or older than 30 days, after a token or MCP server changed, or when the human asks which MCP servers or tools fit the project.
---

# Check and record the integrations

Finds out what the assistant can reach — GitHub or GitLab (also self-hosted) by REST, MCP servers
in the session — and writes the result to `docs/project/integrations.md`, so `act-pr` and
`act-issue` need not guess. Every call is a read; a write capability is reported as "access present,
not tried", never tried (`R-safe-approval`, `topics/live-systems.md` § Repo host and issue tracker).
The CLI tools `gh` and `glab` are not used.

## Steps

1. Run `python .act/scripts/integrations.py check`. It reads the remote and hoster (through
   `forge.py`), where the access comes from (variable names only, never a value), the servers in
   `.mcp.json` and `claude mcp list` (unknown, not an error, if `claude` is missing or slow), and
   probes REST with `whoami`, the project and an issue list of one entry. Where the service shows
   the token's scope for reading, the write rows carry it.
2. Show the table to the human as it is.
3. Map the MCP tools of this session onto the capabilities — only you see them. A tool that reads
   the project, lists issues, creates an issue, comments or opens a PR/MR gets passed on in step 5
   as `--mcp read-issues=<tool name>` (capabilities: `read-project`, `read-issues`, `create-issue`,
   `comment`, `create-pr`). Name what is there; do not call a write tool to test it. A `hint:` line
   in the output (JSON: `catalog_hints`) names the catalog entry for a repo host without a matching
   MCP server: mention it as an option, propose nothing unasked beyond that line (see "Set up from the
   catalog" below).
4. For what is missing or failing, give the concrete cause and fix:
   - No token: the variable for the host — `GITHUB_TOKEN` (or `GH_TOKEN`) for GitHub, `GITLAB_TOKEN`
     for GitLab — in the process environment or in `.env` in the project root. `forge.py` reads
     `.env` (only these names), Claude Code itself does not. `.env` belongs in `.gitignore`; the
     check notes it when it does not. Never ask for the token in chat and never put it on a
     command line (`R-safe-no-secret-cli`).
   - `token scope too small`: which scope the write needs (`repo` on GitHub, `api` on GitLab).
   - `host not confirmed` (hoster unknown or self-hosted): have the human confirm the host name, then
     enter `forge` = `github` or `gitlab` and `forge-host` = that host name (a comma list for several)
     in `docs/ai/config.md` § Git hosting. `forge.py` sends a token only to `github.com`
     (`api.github.com`), `gitlab.com`, a host named there or the host of `ACT_FORGE_API_URL`, so a
     global token never goes to a foreign host; without `forge-host` reads run without a token, and
     `whoami`, `issues --mine` and every write stop with a hint before any request. Never enter it
     unconfirmed.
   - `http only — use https`: the host is confirmed, but the remote (or `ACT_FORGE_API_URL`) is a
     plain `http://` address that is not loopback, so no token goes over it and the same calls stop.
     Switch the address to `https://`; there is no way to release a token over `http://`.
   - HTTP 401/403/404: token expired, wrong host, or no rights on the project.
5. Run `python .act/scripts/integrations.py check --write [--mcp ...]` to write the file (headings in
   in `language-docs`, who checked, the check date). The first time the file is written, add a line for
   it to the docs index `docs/README.md` (`act-commit` step 5). Then journal it:
   `entries.py new ledger "act-integrations: <hoster>, REST <state>, MCP <state>"`.
6. A failure that looks like a pattern (a self-hosted GitLab that does not answer as expected, an
   MCP server that never connects) goes to `feedback.py --add --kind mcp` (or `--kind bug` for a
   fault of the script itself) — the pattern only, no host names, no project names, no token.

## When it runs again

`python .act/scripts/integrations.py status` exits 0 while the file exists and is at most 30 days
old (`--max-age-days`), and 3 with one line "run act-integrations" when it is missing or older.
`act-pr` and `act-issue` call it first and run this skill when it exits 3.

## Propose from the catalog (on request)

`.act/mcp-catalog.md` lists common MCP servers, one `## <id>` entry each: what it serves (`serves`),
when to propose it (`suggest-when`), transport, the kind of access (`auth`: `none`, `token`,
`username-password`, `url`, `oauth`, `connection-string`), what the human has to provide (`options`,
names only), the `claude mcp` command and the `.mcp.json` entry with placeholders, notes and the
`source`/`checked` line. The format per tool (Claude Code, Copilot/VS Code, Cursor, Gemini CLI, Codex)
is at the top of the file.

1. When the human asks ("which MCP servers fit?", "is there an MCP for Jira?") — a `hint:` line alone
   is no request —, read the catalog and pick the entries that fit this project: the repo host and tracker
   (`docs/ai/config.md` § Git hosting, the check output), the stack, an IDE, data files. Say per
   entry in one line why it fits, what it needs from the human (the `options`), and any risk from
   `notes` (write access, beta status, a minimum version). Do not list the whole catalog.
2. An entry whose `checked` date is older than about three months, or whose notes say `unverified` for
   the step at hand, gets a look at its `source` first; say so.
3. Only after a clear "yes" for that entry, set it up:
   - For `token`, `username-password`, `connection-string` name the variable(s) from `options` and where
     they go: the process environment Claude Code is started from (Claude Code reads no `.env`, so a
     `.env` value needs to be exported first) — never ask for the value in chat, never write it on a
     command line or into `.mcp.json` (`R-safe-no-secret-cli`); the config carries `${VAR}` only.
   - For `url` ask for the host or path, for `oauth` say that the sign-in happens in the browser on
     first use (`/mcp` in a session).
   - Run the entry's `claude-command` with the placeholders filled in (a write to the project's
     `.mcp.json`), or write the `claude-json` block into `.mcp.json` yourself if the command does not
     work on this shell. Then `claude mcp list`, and run `check --write` again.
   - An entry that can write to a live system (`github`, `gitlab`, `atlassian`, `linear`, `youtrack`,
     `duckdb` with `--read-write`, `idea`) is used read-only until the human approves a write for this
     exact case (`R-safe-approval`).
4. Setting servers up without being asked is not part of this skill. A server that is missing from the
   catalog or an entry that turned out wrong goes to `feedback.py --add --kind mcp` (pattern only).

## Limits

No write call, not even a harmless-looking one. No token value in chat, journal, file or feedback.
No MCP server is set up without the human's yes for that entry. The result is a snapshot: a token that
expired since is found when the next real action fails.
