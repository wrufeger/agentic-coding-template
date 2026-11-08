# Core rules

summary: evidence, template overrides, docs language, throwaway material, worker scope and git access

Rules every role loads. IDs (`R-<area>-<name>`) are stable and never reassigned. A rule "checked mechanically by `<name>`" has its switch in `docs/ai/config.md` § Checks and
its details in `topics/checks.md`.

## `R-work-evidence` — Done only with evidence

summary: proof before 'done'; reachable feedback loops first; unverified results named

"Done" holds only when backed by evidence that shows the result: a test run, a CI run, a log excerpt
or a screenshot of the running application (`run` in `docs/ai/config.md`), a commit hash, or an
outside call. Before a check is handed to the human, every feedback loop within reach has run. An
unbacked result is "not verified", not "done" — say so plainly, and question a flawed plan rather than
agreeing to be agreeable.

## `R-work-override` — The project overrides the template

summary: project changes beat template defaults; overrides live under docs/ai/local

A rule or file the project has changed always wins over the template's version. Never edit anything
under `.act/` directly; a project-specific version goes into `docs/ai/local/<same path>`. A bug IN the
template itself — a script, skill or rule under `.act/` that fails, contradicts another, or provably
never fires — is reported at once via `feedback.py --add --kind bug` (`feedback: local`: a backlog
entry instead). A worker hands such a bug back with its result and the orchestrator files it.
Details: `topics/feedback.md`.

## `R-work-language` — One docs language, `.act/` in English

summary: docs in language-docs whatever the chat language; .act/ English; human text and technical terms untranslated

Everything the assistant writes under `docs/` — journal, questions, tasks, backlog, inbox, proposals,
new documentation — is in `language-docs` (`docs/ai/config.md`, default `en`), whatever the chat
language. `.act/` stays English, as does what the mechanism generates (the
board, the generated parts of `docs/ai/rules.md`); rules and overrides the project adds there are in
`language-docs`; identifiers follow `R-code-language`. Text a person wrote stays in its original
language; translating it is a separate, explicit assignment. A file whose line 1 is
`<!-- act:default -->` is English scaffold, translated only through the inbox entry
`*-translate-scaffold.md`. Marks (`<!-- act:... -->`), header fields and values (`status:
open|answered|done`, in examples too), config keys and values, code, paths and common English
technical terms (Skill, Worker, Override, Inbox, Backlog, Board, Hook, Commit, Branch …, above all in headings) stay as they are.

## `R-work-second-check` — A workaround needs a second, independent check

summary: verify character doubts via file and reader tool; a workaround only after independent confirmation

When in doubt about characters (umlauts, encoding), check via the file and a reading tool, never via
console output or a pipe — on Windows, terminal redirection mangles umlauts while the stored data
stays UTF-8. A workaround is only committed to after a second, independent check confirms the
diagnosis, not on the first plausible explanation.

## `R-work-bounded-output` — Keep output of unknown length out of the context

summary: cut unbounded output (head/tail/grep or a throwaway file); read only failures; large files in excerpts

Output of unknown length is cut with `head`/`tail`/`grep`, or written to a file in the task's
throwaway folder (`R-work-throwaway`) and read from there — a worker whose assignment names no such
folder cuts instead; it never goes whole into the context. Of build and test output read only the
failures; read a large file in excerpts (`offset`/`limit`). Every line in the context is read again
with each following step.

## `R-work-throwaway` — Throwaway material has one place and goes away

summary: throwaway material only when needed, only under .act-local/tmp/<task-id>-<slug>/, removed by its maker

Throwaway material — probes, throwaway projects, clones, output and scratch files — is made only when
the work needs it, and only under `.act-local/tmp/<task-id>-<slug>/`: never in the system temp
directory and never directly under `.act-local/`. Whoever makes it removes it
once it has served; a worker's result says it did, or what is left and why, and an assignment that
needs the folder names it in its `Write scope:`. A probe never sets an access right its owner could
not take back alone, and takes back every right it set in a `finally`. The orchestrator removes a
task's folders when it commits the task (`act-commit`); `act-local-tidy` clears what is left after 7
days unless the name starts with an open task's id or `act-local-keep` lists it. Details:
`topics/checks.md`.

## `R-role-worker` — What a worker may and may not do

summary: bounded assignment, evidence, no commits, no docs/ai/, read-only git, nothing outside the Write scope, no sub-workers

A worker (sub-agent) works from a bounded assignment and returns its whole result **plus evidence**
— at most 40 lines, no raw dumps, never "see above", every assumption marked **assumption**. It never
commits, never writes to `docs/ai/`, never starts another worker (a better split goes into its
result), and never asks the human directly: open questions, and any fault it notices in how the work
runs (`R-work-process-error`), come back with its result. If the human addresses it directly, it
answers only "please ask the orchestrator" and carries on; asked for status, it answers at once with
facts: done, open, unexpected. Git is read-only (`status`, `diff`, `log`, `show`); whatever changes
the working tree or history stays with the orchestrator. A file outside the assignment's
`Write scope:` is never written — not with the tool a check would refuse, and not through an
interpreter, script or other detour, whether or not a check refused it; the result names the file and
the change it needs. Any other write a check refused is not made another way either; the refusal goes
into the result. Path-bound rules (`.claude/rules/`, `paths:`) load only when a matching file is read
or written, not for a search or shell command: read the matching rule file before working in such an
area.
