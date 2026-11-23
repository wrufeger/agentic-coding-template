---
name: reviewer
description: Adversarial review before a commit — bugs, style, and task fidelity, verdict ALLOW, CONDITIONAL or BLOCK — plus ALLOW/BLOCK on a flagged safeguard call.
copilot-description: Use once per task before it is accepted and committed, and on a flagged safeguard call. Adversarial review of bugs, style and task fidelity; verdict ALLOW, CONDITIONAL or BLOCK.
tier: elevated
reasoning: high
high-variant: true
tools: Read, Bash, Grep, Glob
omitClaudeMd: true
---

Apply the rules from `.act/agents/reviewer.md` before the ones below.
