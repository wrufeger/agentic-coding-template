# Security checklist scaffold

summary: a short list to walk through before a release or when data or exposure changes

Copy the block into `docs/project/security.md`. Tick a line only after looking at the code or the setup; write
"not applicable" with a reason instead of deleting a line. The list does not replace the template's security
checks (`security-check` in `docs/ai/config.md` § Checks); it records the project's own answers.

```markdown
## Security checklist — <date>

- [ ] **Secrets:** none in the repository or its history; `.env` ignored; a `.env.example` without values exists
- [ ] **Input:** every external input (request, file, argument, message) is validated or escaped where it is used
- [ ] **Authentication and access:** each route or command checks who is calling; the default is deny
- [ ] **Data:** personal data is listed (what, where, how long); logs hold identifiers, not the data itself
- [ ] **Dependencies:** a vulnerability check ran (`act-deps`); nothing unmaintained on the critical path
- [ ] **Transport and storage:** HTTPS only; sensitive data encrypted at rest where the stack offers it
- [ ] **Errors:** messages to users hold no stack traces, paths or internals
- [ ] **Backups and recovery:** a restore was tried once; who can do it is written down
- [ ] **Open findings:** <each with owner and date, or "none">
```
