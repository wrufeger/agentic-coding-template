---
name: expert-solver
description: High-reasoning escalation, called only after a worker has failed the same task twice.
copilot-description: Use only after a worker has failed the same task twice, with both attempts and their output. High-reasoning escalation; never a first attempt.
tier: expert
reasoning: max
tools: Read, Edit, Write, Bash, Grep, Glob
omitClaudeMd: true
---

Apply the rules from `.act/agents/expert-solver.md` before the ones below.
