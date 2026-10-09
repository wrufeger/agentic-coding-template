# Feedback to the template author

Detail page for a rule that references it as `topics/feedback.md`. Read this when
`docs/ai/config.md` § Feedback has `feedback` set to anything other than `off`, or when a
template bug needs reporting regardless of that switch (see "Immediate trigger" below).
Mechanism: `.act/scripts/feedback.py` (privacy checks in `feedback_privacy.py`), skill
`act-feedback`.

## What this is for

A derived project can report back what served the **working method** well or was missing — never
the project itself. The test for every entry: would this help someone who will never see this
project? A rule that had to be added because the template lacked it, a workflow that worked well
or kept failing, a script or skill born here that generalizes — that is feedback. A fact about
this project (its name, its stack choice, a number from its data, a quote from its docs) is not.

## Consent, cadence, scope

Three keys in `docs/ai/config.md` § Feedback control this, and none of them is a project fact
either — they only say how the template was configured:

- `feedback`: `off` (default) · `confirm` (show the payload, ask) · `automatic` (send without
  asking) · `manual` (collect, never send on its own — only `--send --force`, i.e. the skill).
- `feedback-cadence`: an upper limit, never an obligation — `manual` · `immediate` · `hourly` ·
  `daily` · `weekly` (default) · `adaptive` (learns from how often reminders get acted on or
  postponed, see `feedback.py`'s own header comment for the exact math). Nothing to report means
  nothing is sent, however short the cadence.
- `feedback-scope`: `a` (metrics) · `b` (rule and structure changes) · `c` (tool usage) — what the
  assistant is allowed to collect **on its own**. A finding written by hand via `--add` always
  goes into the outbox regardless of scope; scope only gates the automatically derived numbers.

## Two paths — do not conflate them

1. **A sentence right after the trigger** (`feedback: <text>`, "send feedback: <text>") **is the
   message itself** — sent via `feedback.py --direct`, unchanged, regardless of the `feedback`
   switch. With `feedback: off`, only this text, the template's own commit hash
   (`.act-lock.json` § `template.commit`) and the project id leave the project — no further
   context. The project id goes with every direct message, whatever the setting (never the repo
   URL — a direct message stays minimal on purpose, unlike the assembled payload below), so
   several messages from the same project can be told apart; it is created when the message is built if
   needed. A reply address goes along only if the human names one in this very request
   (`--contact <email>`, only with `--direct`): it is not stored and never filled in from
   anywhere else, and a mail address inside the text itself is still rejected.
2. **The trigger alone, nothing after it** means: assemble the collected feedback — go through
   `.act/`, the generated bridges and `docs/ai/`, write one entry per finding (`feedback.py --add`,
   two to six sentences), then `--plan` to preview and `--send` to go out under the switches above.

## Immediate trigger: a bug in the template itself

A script or skill under `.act/` failing or doing the wrong thing, an update pulling in something
that should have stayed out (or skipping something it should have added), two of the template's
own rules contradicting each other, or a rule that provably never fires — this is reported **at
once**, independent of `feedback-cadence`: unreported, it keeps hitting every other project
derived from the template. `feedback.py --add --kind bug` bypasses the cadence gate the moment the
entry is stored. It does **not** bypass consent: with `feedback: off`, the entry is stored and
`--add` says so, but nothing leaves the project until someone enables sending — the same one-time,
non-repeated mention as for any other finding under `feedback: off`.

Recurring shapes this takes in practice (patterns to recognize, not a checklist to fill in): a
rule or a file format turned out to be impractical in real use, a workflow the template assumed
had no matching command or skill, a workaround was needed because the intended path did not work.
Each is worth its own entry the moment it happens, not batched for later.

## What a good entry looks like

| Not this | But this |
| :--- | :--- |
| "`app/stores/countries.ts` was missing a return type" | "The TypeScript rule set had no rule for explicit return types" |
| "We switched the project to Kysely" | "A concept with options helped more than a task once, because the decision itself wasn't made yet" |
| "Our customer needs two databases" | "Two same-kind MCP servers with different credentials need separate config entries; nothing said so" |

Nothing that only holds for this project — no project name, no paths, no numbers, no code, no
people. No praise ("works well" helps nobody) — only what concretely helped or was missing.

## Privacy check

Every string that could leave the project — every field of a stored entry, every automatically
collected number's surrounding text, a hand-written `--direct` message — runs through
`feedback_privacy.py` first: credentials-adjacent words, mail addresses, IP addresses, absolute
paths, long hex values, and any URL that is neither the feedback endpoint itself nor github.com. A
match is **not silently stripped**: nothing is sent, and the reason is reported so the entry can be
rewritten without that part.

## Where a send is recorded

Every actual send writes a full copy of its payload to `.act-local/feedback/sent/` — gitignored,
never leaving this checkout. Pending entries and small bookkeeping (project id,
cadence-learning counters) live in `.act-local/feedback/` alongside it. In the project's own,
versioned history, a send instead leaves a one-line journal entry under `docs/ai/work/ledger/`
(via `entries.py`) — date, kind (batch/direct), entry count, schema version, nothing more: never
the entries' content or their own titles.
