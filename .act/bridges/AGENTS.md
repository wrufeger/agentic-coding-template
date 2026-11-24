Read `docs/ai/local/rules.md` first, then the files it imports.

That file — not this one — carries the actual rules. `AGENTS.md` exists only because tools
without an `@`-import mechanism look for it by convention; the project always overrides the
template (`R-work-override`).

## GitHub Copilot: delegate by default

Under GitHub Copilot, the cases `R-cost-delegate` names for a worker are a must, not an option; the
roles are the custom agents under `.github/agents/`:

- Research across more than three files or an unknown spot goes to `explorer`, a test, probe or
  smoke-test run to `quick-check`, the review before a commit to `reviewer`: at once, before the
  main session reads the material itself.
- Independent parts (separate files, one review per spot, separate test runs) start as separate
  subagent calls in the same turn, not one after another.
- Every assignment starts with the header of `R-cost-delegate` (`Write scope:`, `Cap:`, `Tests:`
  where something runs).
- A known spot, a few tool calls, a small change, an entry under `docs/ai/` and every commit stay
  with the main session (`R-role-main`, `R-code-commit`).

This section is for the main session only: a worker never starts another worker (`R-role-worker`).
