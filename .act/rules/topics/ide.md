# IDE MCP server

Detail page for a rule that references it as `topics/ide.md`. Loaded only when a session start
detects a connected IDE MCP server (JetBrains `idea` and similar names in `.mcp.json`, the Claude
settings or `~/.claude.json`, or Claude Code's own `ide` server — see `checks/session.py`'s
`_ide_mcp_connected`). Not loaded otherwise; nothing here applies to a project without one.
Claude Code's `ide` server offers `getDiagnostics` (read, fine for anyone) and `executeCode`
(orchestrator only, like every tool that runs code).

Tool names as of the JetBrains MCP server checked 2026-09-26:

- **Rename** a symbol via `rename_refactoring`, not search-and-replace over the text — orchestrator
  only, or a worker whose assignment carries no `Write scope:` line at all: the tool writes
  wherever the symbol is used, which a bounded `Write scope:` cannot vouch for in advance, so the
  `ide-mcp` check (`docs/ai/config.md` § Checks) blocks it for a worker with one.
- **Moving** a file that documentation points to: switch off the IDE's "search in comments and
  strings" option first, or check `git diff --word-diff` over the `*.md` files afterwards — that
  option has rewritten backtick paths and ordinary prose in Markdown.
- **Calls and dependencies** via `search_symbol` → `analyze_calls`; a code pattern via
  `search_structural` instead of a regex. More precise than `grep` and fewer follow-up calls. Both
  are read-only and open to every worker.
- **After editing**, run `lint_files` on the changed files; look up findings with
  `get_inspections`, and `apply_quick_fix` only for an unambiguous case. This is evidence for the
  worker to report — it is **not** a configured lint in the sense of `R-code-commit`: it does not
  run in CI, and depends on the IDE's own settings.
- `build_project` (a compiled language such as Java, Kotlin) and `xdebug_*` (during `act-bug`, for
  PHP) run code — orchestrator only, never a worker (`R-role-worker`'s execution boundary; the
  `ide-mcp` check blocks both for any worker).
- **Do not use:** `execute_terminal_command`, `execute_run_configuration`, `apply_patch`,
  `create_new_file` — use the standard tools (Bash, Write, Edit) instead; the template's checks
  are built around those. The `ide-mcp` check (`docs/ai/config.md` § Checks) still covers the IDE
  tools, but only as far as their arguments can be evaluated.
- Writing to a database only with approval (`R-safe-approval`) — reading is free.
- The IDE is not always running: if the server does not answer, fall back to the standard tools;
  do not wait for it.
