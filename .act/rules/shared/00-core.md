# Core rules

summary: evidence over claims, template overrides, docs language, throwaway material, worker scope and git access

Rules every role loads — orchestrator and every sub-agent. IDs (`R-<area>-<name>`) are stable and
never reassigned, even if the wording changes later. Companion files in this layer:
`10-safety.md`, `20-code.md`.

## `R-work-evidence` — Done only with evidence

summary: test run, CI run, log excerpt, screenshot, commit hash or outside call as proof; every reachable feedback loop before the human's; naming unverified results

"Done" holds only when backed by evidence that shows the result: a test run, a CI run, a log
excerpt or a screenshot of the running application, a commit hash, or an outside call. Before a
check is handed to the human, every feedback loop within reach has run — tests, CI status, logs,
the running application (`run` in `docs/ai/config.md`). An unbacked result is "not verified", not
"done" — say so plainly, and question a flawed plan rather than agreeing to be agreeable.

## `R-work-override` — The project overrides the template

summary: project changes beat template defaults; overrides live under docs/ai/local

A rule or file the project has changed always wins over the template's version. Never
edit anything under `.act/` directly; a project-specific version goes into
`docs/ai/local/<same path>` instead. A bug IN the template itself — a script, skill or rule under
`.act/` that fails, contradicts another, or provably never fires — is reported at once via
`feedback.py --add --kind bug`. A worker does not file it itself: it hands such a bug back with its
result, and the orchestrator files it. Details in `topics/feedback.md`.

## `R-work-language` — One docs language, `.act/` in English

summary: every docs/ai entry and new doc in language-docs whatever the chat language; .act/ English; human text untranslated; scaffold translated once, English technical terms kept

Everything the assistant writes under `docs/` is in `language-docs` from `docs/ai/config.md`
(default `en`) — journal, questions, tasks, backlog, inbox, proposals and new documentation alike,
whatever language the chat runs in and whoever it runs with, so the record reads as one. `.act/`
stays English, and so does what the mechanism generates (the board under `.act-local/`,
`docs/ai/rules.md`, whose generated parts the template keeps current); rules and overrides the
project adds there are the project's text, in `language-docs`; identifiers follow `R-code-language`. Text
a person wrote stays in its original language: translating it is a separate, explicit assignment,
never part of another task. A file whose line 1 is `<!-- act:default -->` is scaffold in the
template's English; it is translated only through the inbox entry `*-translate-scaffold.md`. Marks
(`<!-- act:... -->`), header fields and their values (`status: open|answered|done` stays English,
in examples too), config keys and values, code and paths stay as they are, since the mechanism
reads those, never the words; so do common English technical terms (Skill, Worker, Override,
Inbox, Backlog, Board, Hook, Commit, Branch …), above all in headings.

## `R-work-second-check` — A workaround needs a second, independent check

summary: verify character/encoding doubts via file and reader tool, never console or a pipe; a workaround only after independent confirmation

When in doubt about characters (umlauts, encoding), check via the file and a reading tool, never
via console output or a pipe — on Windows, terminal redirection mangles umlauts while the stored
data stays correct UTF-8. More generally: a workaround is only committed to after a second,
independent check confirms the diagnosis, not on the first plausible explanation.

## `R-work-bounded-output` — Keep output of unknown length out of the context

summary: head/tail/grep or a file in the system temp directory for unbounded output; read only the failures of a build or test run; large files in excerpts

Output whose length is not known beforehand is cut with `head`/`tail`/`grep`, or written to a file in
the system temp directory (writable for every worker, as a path written out) and read from there, never taken whole into the context.
Build and test output goes the same way: read only the failures. A large file is read in excerpts
(`offset`/`limit`), not whole. Every line that enters the context is read again with each following
step.

## `R-work-throwaway` — Throwaway material has one place and goes away

summary: probes, throwaway projects and scratch files in the system temp directory, else .act-local/tmp/<task-id>-<slug>/; removed with the task's commit; act-local-tidy clears the rest; mechanically checked

Throwaway material — probes, throwaway projects, scratch files — goes into the system temp
directory. Where the tool refuses that to a worker, it goes into `.act-local/tmp/<task-id>-<slug>/`,
never directly under `.act-local/`. The orchestrator removes a task's folders when it commits the
task (`act-commit`). At session start, `act-local-tidy` removes what is left after 7 days unless its
name starts with an open task's id or `act-local-keep` lists it (`docs/ai/config.md` § Checks).
Details: `topics/checks.md`.

## `R-role-worker` — What a worker may and may not do

summary: bounded assignment, evidence and marked assumptions, no commits, no docs/ai/, read-only git, no refused write made another way, no sub-workers

A worker (sub-agent) works from a bounded assignment and returns a result **plus evidence**, at
most 40 lines, no raw dumps, every assumption it made marked **assumption**. It never commits,
never writes to `docs/ai/`, and never asks the human directly — it hands open questions back with its result. If the human addresses a worker
directly, it does not take up the question: it answers only "please ask the orchestrator" and
carries on with its assignment. Asked for status, it answers at
once with facts: done, open, unexpected. Git access is read-only (`status`, `diff`, `log`,
`show`); every command that changes the working tree or history stays with the orchestrator.
A write a check refused is never made another way — not through an interpreter, a script, another
tool or a detour; the worker reports the refusal with its result.
A worker never starts another worker: if the task would be better split, it says so in its result
and the orchestrator decides.
