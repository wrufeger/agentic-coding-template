# Document guide

summary: which project document to write when, with short scaffolds for a decision record, an API spec, a security checklist and a deployment note

Read by `act-audit-docs` (step 3, when a wave produced something that has no document yet) and by anyone asked
"where does this go?". Not a format the skills enforce: the files here are starting points to copy into
`docs/project/` and shorten or extend. Written in the project's documentation language once copied
(`R-work-language`); every new file gets its line in the `README.md` of its folder (`R-docs-order`).

## Pick by answering three questions

1. **What happened?** A choice between options was made → decision record (`adr.md`). An interface other code or
   other people call was added or changed → API spec (`api-spec.md`). Something is exposed, stores data or
   handles credentials → security checklist (`security-checklist.md`). The way the project gets to a server or a
   store changed → deployment note (`deployment.md`).
2. **Who reads it later?** The next developer (decision record, API spec, deployment), a reviewer or auditor
   (security checklist), or an operator (deployment).
3. **Does it stay true?** A document that describes the current state (API spec, deployment) is kept current by
   `act-audit-docs`; a decision record is never rewritten, a later decision supersedes it.

| Scaffold | Copy to | When |
| :--- | :--- | :--- |
| `adr.md` | `docs/project/decisions.md` (one row or section per decision) | a decision with options and a reason |
| `api-spec.md` | `docs/project/api.md` | an endpoint, command or library interface other code depends on |
| `security-checklist.md` | `docs/project/security.md` | before the first release, and when data or exposure changes |
| `deployment.md` | `docs/project/deployment.md` | the project runs somewhere other than the developer's machine |

Do not copy a scaffold for its own sake: a project without an API has no API spec. A file stays at most about
300 lines; past that it becomes a folder with a `README.md`.
