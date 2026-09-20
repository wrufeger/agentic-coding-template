# Rules

Yours to change: uncheck a rule to switch it off, drop an import line to switch off its whole
area, add your own below (`R-work-override`).

## Shared — every role, including sub-agents


@.act/rules/shared/00-core.md
  - [x] `R-work-evidence`
  - [x] `R-work-override`
  - [x] `R-role-worker`

@.act/rules/shared/10-safety.md
  - [x] `R-safe-approval`
  - [x] `R-safe-no-secret-cli`
  - [x] `R-safe-no-secret-diff`
  - [x] `R-safe-no-shell-delete`
  - [x] `R-safe-block`
  - [x] `R-safe-foreign-text`

@.act/rules/shared/20-code.md
  - [x] `R-code-language`
  - [x] `R-code-encoding`

## Orchestrator only — the main session

Planning, delegating, committing, talking to the human — nothing a sub-agent needs. **Deliberately
not `@`-imported**: that would load them into every sub-agent, which is what this layering avoids.
The dispatcher hands them to the main session; without one, the main session reads them itself.


`.act/rules/orchestrator/00-role.md`
  - [x] `R-role-main`
  - [x] `R-role-escalate`

`.act/rules/orchestrator/10-work.md`
  - [x] `R-work-record-now`
  - [x] `R-work-session-start`
  - [x] `R-work-idea-first`
  - [x] `R-work-config`
  - [x] `R-work-handover`

`.act/rules/orchestrator/20-human.md`
  - [x] `R-human-inbox-first`
  - [x] `R-human-ask`
  - [x] `R-human-text`
  - [x] `R-human-external`

`.act/rules/orchestrator/30-cost.md`
  - [x] `R-cost-delegate`
  - [x] `R-cost-wait`
  - [x] `R-cost-script`
  - [x] `R-code-commit`

## Overrides

<!-- replaces `R-...`: <your version> -->

## Own rules

<!-- one item per rule, no counterpart in the template -->
