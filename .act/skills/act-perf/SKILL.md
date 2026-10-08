---
name: act-perf
description: Use when something is reported as slow or asked to speed up a named page, query or endpoint. Ends with that one part measurably faster, shown by numbers from before and after a single change. Not for behavior-preserving restructuring - use act-refactor.
---

# Improve performance

Improves one concrete, named part of the system — a page, a query, an endpoint — based on
measurements, not guesses. Core rule: **measure, then change**; no measurement beforehand is a
claim, not an improvement.

1. **Name the symptom and the goal** — what's slow, for whom, what counts as good enough, as a
   number ("under 300 ms"), not a feeling.
2. **Measure and record the baseline** before changing anything: tool, conditions (environment,
   data volume, repetitions), value.
3. **Find the cause** — profile, query plans, network waterfall, render breakdown, whatever fits
   the symptom — before designing a change.
4. **Make one change** addressing exactly that cause; several at once and the effect can't be
   attributed.
5. **Measure again**, same conditions and tool as step 2.
6. **Compare against the goal.** Not enough: back to step 3 with the next cause, one change per
   round.
7. **Prove and close** — required checks (`docs/ai/config.md` § commands), before/after numbers
   into `docs/ai/work/ledger/`, then `act-commit`.

No gain after the change: the change is reverted, not kept on principle; readability never trades
for a micro-optimization nobody can read afterward.
