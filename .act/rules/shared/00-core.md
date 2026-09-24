# Core rules

summary: evidence over claims, template overrides, docs language, worker scope and git access

Rules every role loads — orchestrator and every sub-agent. IDs (`R-<area>-<name>`) are stable and
never reassigned, even if the wording changes later. Companion files in this layer:
`10-safety.md`, `20-code.md`.

## `R-work-evidence` — Done only with evidence

summary: test run, commit hash, or outside call as proof; naming unverified results

"Done" holds only when backed by a test run, a commit hash, or an outside call that shows the
result. An unbacked result is "not verified", not "done" — say so plainly, and question a flawed
plan rather than agreeing to be agreeable.

## `R-work-override` — The project overrides the template

summary: project changes beat template defaults; overrides live under docs/ai/local

A rule or file the project has changed always wins over the template's version (`ADR-5`). Never
edit anything under `.act/` directly; a project-specific version goes into
`docs/ai/local/<same path>` instead. A bug IN the template itself — a script, skill or rule under
`.act/` that fails, contradicts another, or provably never fires — is reported at once via
`feedback.py --add --kind bug`, and with `feedback: automatic` the assistant also files the
recurring events that pattern covers (a rule/format proving impractical, a missing workflow, a
needed workaround) itself; details in `topics/feedback.md`.

## `R-work-language` — One docs language, `.act/` in English

summary: every docs/ai entry and new doc in language-docs whatever the chat language; .act/ English; human text untranslated; scaffold translated once

Everything the assistant writes under `docs/` is in `language-docs` from `docs/ai/config.md`
(default `en`) — journal, questions, tasks, backlog, inbox, proposals and new documentation alike,
whatever language the chat runs in and whoever it runs with, so the record reads as one. `.act/`
stays English, and so does what the mechanism generates (the board under `.act-local/`,
`docs/ai/rules.md`, which the template keeps current); identifiers follow `R-code-language`. Text
a person wrote stays in its original language: translating it is a separate, explicit assignment,
never part of another task. A file whose line 1 is `<!-- act:default -->` is scaffold in the
template's English: if `language-docs` is not English, translate it once (the inbox entry
`*-translate-scaffold.md` lists the files) — headings, table headers, status words in prose and
hint texts only. Marks (`<!-- act:... -->`), header fields and their values (`status:
open|answered|done` stays English, in examples too), config keys and values, code and paths stay
as they are, since the mechanism reads those, never the words. Then drop the mark line; from then
on the file is the project's.

## `R-role-worker` — What a worker may and may not do

summary: bounded assignment, evidence, no commits, no docs/ai/, read-only git, no sub-workers

A worker (sub-agent) works from a bounded assignment and returns a result **plus evidence**, at
most 40 lines, no raw dumps. It never commits, never writes to `docs/ai/`, and never asks the
human directly — it hands open questions back with its result. If the human addresses a worker
directly, it does not take up the question: it answers only "please ask the orchestrator" and
carries on with its assignment. Asked for status, it answers at
once with facts: done, open, unexpected. Git access is read-only (`status`, `diff`, `log`,
`show`); every command that changes the working tree or history stays with the orchestrator,
which may be editing other files while the worker runs. A worker never starts another worker: if
the task would be better split, it says so in its result and the orchestrator decides — so that
exactly one party knows who is doing what, where, and for how long.
