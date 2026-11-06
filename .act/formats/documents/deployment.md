# Deployment note scaffold

summary: how the project gets to where it runs, how to check it and how to go back

Copy the block into `docs/project/deployment.md`. Writing to a live system needs the owner's dated approval for
the exact case (`R-safe-approval`); this note describes the way, it grants nothing. Keep every command copyable
and free of secrets: name the variable or file that holds one.

```markdown
## Deployment

- **Environments:** <name — where it runs — who may deploy>
- **Build:** <command or pipeline; what it produces>
- **Configuration:** <which variables or files, where they live, who maintains them (names only, no values)>
- **Release steps:** <numbered, each a command or a click path>
- **Check after release:** <what to open or run, and what "healthy" looks like>
- **Rollback:** <the way back, how long it takes, what cannot be undone (data, migrations)>
- **Backups:** <what is saved, how often, where, last restore test>
- **Contacts:** <role or team, not private data>
```
