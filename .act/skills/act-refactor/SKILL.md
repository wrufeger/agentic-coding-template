---
name: act-refactor
description: Use when asked to refactor, clean up or restructure existing code without changing what it does. Works in small steps with tests after each one, after stating goal and scope and checking the test net. Not for making code faster - use act-perf.
---

# Restructure without changing behavior

Restructures existing code to stay readable, consistent, or easier to extend — same result as
before. Not for changing functionality or "modernizing" just because code looks old, and not
without a test net: missing one, run `act-test-gap` for the area first, or decline the refactor.

1. **Name the goal** in one sentence — shorter, less duplication, clearer responsibility, a
   swappable dependency.
2. **Bound the scope** — which files/modules are in, which explicitly aren't. Grows past this
   during the work: stop and re-cut instead of continuing "along the way."
3. **Check the test net** (`docs/project/testing.md`). Doesn't cover the affected behavior: run
   `act-test-gap` first, then continue here.
4. **Restructure in small steps** — one rename, one extraction, one move at a time, never one
   large patch.
5. **Test after every step**; the suite from step 3 stays green before the next step starts, a
   red intermediate state gets fixed immediately.
6. **Compare behavior at the end** — spot-check inputs/outputs, plus the full required checks
   (`docs/ai/config.md` § commands), then `act-commit`.

A behavior change found along the way is a separate, later commit, never folded into this one; a
new library or pattern only when the goal from step 1 requires it (`docs/project/coding_rules.md`).
