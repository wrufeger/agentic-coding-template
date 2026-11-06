# Decision record scaffold

summary: one decision with the options considered and the reason, short enough to read in a minute

Copy the block into `docs/project/decisions.md` (one section per decision, newest last) or into a file of its
own under `docs/project/decisions/` once there are many. Fill every line or delete the line; never leave the
placeholders.

```markdown
## <number> <Short decision title>

- **Date:** <YYYY-MM-DD>
- **Status:** proposed | accepted | superseded by <number>
- **Context:** <what forced a decision; the constraints that matter>
- **Options:** <option A>; <option B>; <option C — each with its main cost>
- **Decision:** <the chosen option, in one sentence>
- **Reason:** <why it beats the others here>
- **Consequences:** <what becomes easier, what harder, what must follow>
```

A decision is never edited after it is accepted, apart from its status; a changed mind is a new record that
names the old one.
