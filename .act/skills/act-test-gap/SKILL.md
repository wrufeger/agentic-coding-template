---
name: act-test-gap
description: Find untested areas in a scope, prioritize by risk, and close the gaps after approval - measure what's covered, propose a prioritized list, write targeted tests instead of chasing coverage percentages. Use when asked to find test gaps, check test coverage for an area, or backfill tests for existing code.
---

# Find and close test gaps

Finds areas without (sufficient) test coverage, prioritizes them by risk, and closes them after
approval. Coverage numbers only locate blind spots — reporting a percentage as the result isn't
the goal, and neither is a test for trivial code (getters, constants, pass-through).

1. **Measure what exists.** Which areas have tests, which don't (`docs/project/testing.md`, a
   coverage report if one exists).
2. **Prioritize by risk**, not by percentage: money, auth/permissions, and data-loss-prone code
   first, then code changed often (`git log`), rarely touched code last.
3. **Propose the gap list before writing anything** — area, risk, reason. Standalone assignment:
   get the human's approval on which gaps to close; as a precondition inside `act-refactor`, that
   assignment's approval for the area is enough.
4. **Pick the seam** each test exercises before writing it, one interface per test — an
   implementation detail re-breaks on the next refactor, a seam doesn't.
5. **One behavior per test**, named for what the code should do, not what it happens to do.
6. **Required checks green** with the existing suite (`docs/ai/config.md` § commands), then
   `act-commit`.

A test that only pins the implementation instead of the wanted behavior doesn't get written, even
if it turns a line green.
