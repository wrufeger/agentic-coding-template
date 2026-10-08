---
name: act-integrations
description: Use when asked what GitHub or GitLab access exists, before act-pr or act-issue when docs/project/integrations.md is missing or older than 30 days, after a token or MCP server changed, or when asked which MCP servers or tools fit the project. Records access read-only; sets up a catalog server only after a yes.
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
   catalog" below, and references/catalog.md).
4. For what is missing or failing, give the concrete cause and fix. Read `references/failure-causes.md`:
   no token, `token scope too small`, `host not confirmed`, `http only — use https`, HTTP 401/403/404.
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

Only when the human asks ("which MCP servers fit?", "is there an MCP for Jira?"); a `hint:` line alone
is no request. Read `references/catalog.md` for the catalog format, picking entries, the age check and the
set-up steps; a server is set up only after a clear "yes" for that entry.

## Limits

No write call, not even a harmless-looking one. No token value in chat, journal, file or feedback.
No MCP server is set up without the human's yes for that entry. The result is a snapshot: a token that
expired since is found when the next real action fails.
