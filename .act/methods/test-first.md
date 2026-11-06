# Working method — test-first

summary: a red test before every behavior change, and a test for every acceptance criterion

Switched on by `methods: test-first` in `docs/ai/config.md` (§ Scope). Group IDs (`MR-test-first-<name>`)
are stable and never reassigned. Applies to everyone who changes behavior, and to the `reviewer`.

## `MR-test-first-red-first` — A failing test comes before the code

summary: write the test, see it fail for the right reason, then change the code

- Every change of behavior (a feature, a fix, a changed rule) starts with a test that names the expected
  behavior and fails before the change. Run it and look at the failure: it must fail because the behavior is
  missing, not because of a typo or a missing import.
- Then write the least code that makes it pass, run the whole affected suite, and only then tidy up.
- No test is needed where nothing executes: documentation, configuration text, a change covered by tests
  that already pass before and after it (a pure move or rename). Say in the report which of these applied.
- A spike or throwaway probe may come first; it is marked as one, and the test follows before the real
  change is made.

## `MR-test-first-criteria-tests` — Every acceptance criterion has a test

summary: map each criterion to at least one test; the reviewer checks the mapping

- A task, backlog item or story with acceptance criteria gets at least one test per criterion. The report
  lists criterion and test side by side; a criterion that cannot be tested names the manual check that
  stands in for it.
- The `reviewer` checks the mapping: a criterion without a test or a named check is a finding, as is a test
  that passes without the change it is meant to prove.
