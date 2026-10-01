---
name: act-bug
description: Fix a reported bug - reproduce it, localize the cause, then prove the fix with a test that is red before the change and green after. Use when a bug is reported, something is broken, or asked to debug specific behavior.
---

# Fix a bug

Fixes a bug with unambiguous evidence: a test that shows it before the fix and not after. Not for
cleanup found along the way, and not for a fix nobody could actually trigger.

1. **Reproduce first.** Search only once the bug triggers — locally, as a test case, or from a log
   excerpt the human gives. No reproduction yet: skip straight to the report below.
2. **Localize.** Affected layer, since when (`git log`, `git bisect` between known-good and current).
   Cause not obvious after a quick look: delegate the hypothesis search to the `debugger` role
   instead of guessing.
3. **Name the cause**, not just where it surfaces. Several candidates: check the likeliest first.
4. **Pick the seam.** Before writing the test, decide which interface it will exercise — one seam
   per cycle, not an implementation detail. That's what keeps the test from re-breaking on the next
   refactor.
5. **Red test at that seam**, before touching the fix. Already green: reproduction was incomplete or
   the cause was named wrong — back to step 1 or 3.
6. **Fix.** Smallest change at the named cause, no surrounding rebuild.
7. **Green test plus the project's required checks** (`docs/ai/config.md` § commands), then
   `act-commit`.

Can't reproduce it: document what was reported, what was tried, and where reproduction failed
instead of fixing on suspicion; ask the human when something's missing (credentials, test data, a
specific environment). Anything else noticed along the way goes to the backlog, not into this
assignment — booked with its open decisions per `inbox-decisions` (`R-human-ask`).
`R-role-escalate` applies unchanged — two failed rounds at the same thing, then the expert role,
never a third identical attempt.
