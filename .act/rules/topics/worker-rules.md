# Worker rules without the orchestrator rules

Detail page for how a worker (sub-agent) gets its rules. Read it when a worker seems to lack a rule,
when a role file is changed, or when `CLAUDE.md` grows large.

## What happens

The orchestrator rules (`.act/rules/orchestrator/`) only concern the main session, yet `CLAUDE.md`
loads them into every worker start as well. The template's roles therefore carry
`omitClaudeMd: true` in their frontmatter (`.act/bridges/agents/`, also on the generated `-high`
variants): Claude Code then loads no `CLAUDE.md` level for them. A `SubagentStart` hook hands the
worker what it needs instead.

- The hook is `dispatch.py SubagentStart --worker-rules <i>`, six fixed entries in
  `.claude/settings.json` (`<i>` = 1..6, from `.act/bridges/settings.hooks.json`). The plain
  `SubagentStart` entry stays for the usage and event log.
- It acts only if the role file of the started `agent_type` (`.claude/agents/<type>.md`, else
  `~/.claude/agents/<type>.md`) says `omitClaudeMd: true`. Any other agent (`general-purpose`, an own
  role without the field, `omitClaudeMd: false`) loads `CLAUDE.md` itself and gets nothing here.
- Content: what `CLAUDE.md` would have loaded — the user level `~/.claude/CLAUDE.md`, the project
  `CLAUDE.md`, `CLAUDE.local.md`, with all `@`-imports followed — except every import whose target lies
  below `.act/rules/orchestrator/` (or its override under `docs/ai/local/rules/orchestrator/`), found by
  the path. The rest of `docs/ai/rules.md` stays, so an unchecked rule is still off.
- Claude Code moves a hook string longer than 10,000 characters into a file and shows a short preview
  only, so the text is cut into parts of at most 9,500 characters (at file boundaries, a long file at
  `## ` headings); entry 6 carries any remainder, which Claude Code then moves into a file.
- `python .act/scripts/rules.py --worker` shows the parts: characters and sources per part, the total, and
  the size of the full `CLAUDE.md` load for comparison.

## Limits

- Claude Code before 2.1.271 does not know `omitClaudeMd` and ignores it: the worker loads `CLAUDE.md`
  and gets the rules a second time. That only costs tokens.
- Without Python 3.9+ the hook prints nothing; a worker then has no rule text, and the mechanical checks
  are inactive too.
- Failure: any exception while assembling gives one fixed sentence (first entry only) telling the worker
  to read `CLAUDE.md`, `docs/ai/rules.md` and the files it imports from `.act/rules/shared/` itself and to
  skip the orchestrator directory. The hook never exits non-zero.
- Only the user level, the project `CLAUDE.md` / `.claude/CLAUDE.md` and `CLAUDE.local.md` are assembled;
  `CLAUDE.md` files in parent folders and `.claude/rules/` files are not.
- A project with very large rule files can need more than six parts; the overflow lands in a file.

## Turning it off

Remove `omitClaudeMd: true` from the role files (or set `omitClaudeMd: false`; `update.py` adds the line
only where none exists). The hook then delivers nothing for that role, and it loads `CLAUDE.md` as before.
