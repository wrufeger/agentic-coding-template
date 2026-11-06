# Working method — spec-first

summary: a written specification with numbered, checkable acceptance criteria before the code

Switched on by `methods: spec-first` in `docs/ai/config.md` (§ Scope). Group IDs (`MR-spec-first-<name>`)
are stable and never reassigned. The specifications ("stories") live in `docs/project/stories/`.

## `MR-spec-first-story` — A story comes before the code

summary: one file per feature or behavior change, with goal, numbered criteria and a status

- Before code for a feature or a change of behavior, a story is written to `docs/project/stories/<slug>.md`
  (the language is `language-docs`): the goal in a few sentences, the acceptance criteria numbered `AC1`,
  `AC2` …, and a `status:` line with `draft`, `approved`, `built` or `verified`.
- Code starts when the story is `approved` by the human. A request that is small enough to be one sentence
  does not need a story; say so and go ahead.
- A change of the requirement changes the story first, then the code. The story and the code never disagree
  about what is wanted.

## `MR-spec-first-criteria` — Criteria can be checked

summary: every criterion is observable and has a named check or test

- A criterion states something that can be seen or measured, with the input and the expected result ("a
  login with a wrong password shows the message and creates no session"), not a quality word ("works well").
- Each criterion names how it is checked: a test, or a manual step someone can repeat. The report for the
  work lists every criterion with its evidence (`R-work-evidence`); the story's status moves to `built`
  when the code is in and to `verified` when each criterion has its evidence.

## `MR-spec-first-storage` — Where the stories live

summary: docs/project/stories/, one file per story, index once there are five

- Stories sit in `docs/project/stories/`, one file per story, named for the feature, no running numbers.
  With five or more files the folder has a `README.md` with one line each (`R-docs-order`).
- A story stays as the description of the behavior while the feature exists; it is deleted when the
  feature is removed.
