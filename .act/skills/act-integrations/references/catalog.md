# Propose and set up MCP servers from the catalog

Read from `SKILL.md` when the human asks which MCP servers fit, or after a `hint:` line led to a request.

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
