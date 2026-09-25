# Rules

Yours to change: uncheck a rule to switch it off, drop an import line to switch off its whole
area, add your own below (`R-work-override`). The imported files load whole, so an unchecked rule
is **off** — ignore its text even though it is loaded. A `replaces` line below wins over the
template text of its rule, checked or not.

## Shared — every role, including sub-agents


@../../.act/rules/shared/00-core.md
  - [x] `R-work-evidence`
  - [x] `R-work-override`
  - [x] `R-work-language`
  - [x] `R-work-second-check`
  - [x] `R-role-worker`

@../../.act/rules/shared/10-safety.md
  - [x] `R-safe-approval`
  - [x] `R-safe-no-secret-cli`
  - [x] `R-safe-no-secret-diff`
  - [x] `R-safe-no-secret-log`
  - [x] `R-safe-no-shell-delete`
  - [x] `R-safe-git-reset`
  - [x] `R-safe-block`
  - [x] `R-safe-foreign-text`

@../../.act/rules/shared/20-code.md
  - [x] `R-code-language`
  - [x] `R-code-encoding`
  - [x] `R-code-tools`
  - [x] `R-code-version`

Imports resolve relative to this file (`docs/ai/`), hence the `../../`. Check what Claude Code
actually loads with `python .act/scripts/rules.py --imports`.

## Coding — every role that writes or reviews code

@../project/coding_rules.md

## Orchestrator only — the main session

Applies to the main session only — workers skip this section.

@../../.act/rules/orchestrator/00-role.md
  - [x] `R-role-main`
  - [x] `R-role-escalate`

@../../.act/rules/orchestrator/10-work.md
  - [x] `R-work-record-now`
  - [x] `R-work-session-start`
  - [x] `R-work-idea-first`
  - [x] `R-work-config`
  - [x] `R-work-handover`

@../../.act/rules/orchestrator/20-human.md
  - [x] `R-human-inbox-first`
  - [x] `R-human-ask`
  - [x] `R-human-chat`
  - [x] `R-human-language`
  - [x] `R-human-text`
  - [x] `R-human-external`

@../../.act/rules/orchestrator/30-cost.md
  - [x] `R-cost-delegate`
  - [x] `R-cost-wait`
  - [x] `R-cost-script`
  - [x] `R-code-commit`

## Overrides
<!-- act:overrides -->

<!-- replaces `R-...`: <your version> -->

## Own rules
<!-- act:own-rules -->

<!-- one item per rule, no counterpart in the template -->
