# Safeguard blocks

Detail page for `R-safe-block` (`.act/rules/shared/10-safety.md`). Read this whenever a tool
flags a request or an action as risky — a guardrail, a content filter, a permission escalation.

## The escalation path

1. Don't abort without cause. Check first whether the flag is a false positive for this concrete
   project context.
2. If it's justified: check whether a more precisely reasoned, smaller-grained, or milder
   phrasing reaches the actual work without touching the trigger — this step applies only to the
   first of the two cases below, never to the second.
3. Still important and still flagged: hand it to a stronger or differently-tuned model — the
   `reviewer` role — instead of permanently changing the orchestrator's own context. A worker
   doesn't start that role itself; it hands the case back to the orchestrator.
4. Still flagged, and it touches something only the human can do: record it as an inbox entry for
   the human — `docs/ai/inbox/U<n>-<slug>.md` (`entries.py new todo`) with `for:` naming the human and
   `status: open`, context plus the exact step — instead of forcing it. Never as a task under
   `docs/ai/work/tasks/`: that is the assistant's own queue.

## Two different cases — do not conflate them

The four steps above apply to a warning that hooks onto the **request** — there, a more precise,
smaller-grained phrasing is legitimate and usually gets there. If the tool instead reports that
the check reacts to the **conversation so far** and a fresh attempt won't help, rephrasing is
pointless and looks like evasion: report the block to the human, with what it prevented. They
decide on a permission mode or a new conversation — restarting with the same history loaded does
not help, since the history is the trigger. Work already done stays exactly where it is; nothing
gets half-forced through.

## A different tool is not evasion

"Don't rephrase and retry" means the same action in new wrapping. Trying the same change through a
**different mechanism** — the assistant's own file tools instead of a shell command — is the
obvious next step instead, and is often already the fix. Try it once, then report.

## Preventing is cheaper than any of these loops

- **Never a secret on the command line** (`R-safe-no-secret-cli`) — neither as an argument nor as an
  inline assignment, not even a throwaway or test value, not even "just briefly": nobody can tell
  from a call that the token was made up.
- **No recursive delete from the shell** (`R-safe-no-shell-delete`) — the classic trigger, and at
  worst the classic accident too.
- **Word assignments mechanically.** Describe what happens ("not applied", "excluded", "stays
  deleted"), not in combat imagery ("lock out", "kill", "choke off"). Costs nothing and gives a
  check nothing to react to.
- **Avoid stacking.** Harmless alone doesn't mean harmless together — autonomous outbound sending,
  token generation, and delete logic in the same block of work read differently together than
  apart. Where it's possible: one after another, in separate blocks, each with its own evidence.

## Every block gets logged

Every block gets logged — even a harmless one: date, what was blocked, the message's wording, the
hypothesis about the cause, and the rule that follows from it, into the journal
(`docs/ai/work/ledger/`); on repeat, additionally as a failure analysis under
`docs/project/incidents/` (create the folder if it doesn't exist yet). A block without an entry repeats itself,
because nobody remembers what triggered it.
