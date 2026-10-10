# act-audit-docs as a workflow script

Claude Code only (its `Workflow` tool), and only when the human asks for the workflow variant in so many
words: the script starts many workers at once, and that is the human's call — naming the skill is not
such a request. The script is `workflow.js` beside `SKILL.md`; the project copy lies at
`.claude/skills/act-audit-docs/workflow.js`, and a project override at
`docs/ai/local/skills/act-audit-docs/workflow.js` wins, as for any skill file.

1. Step 1 of the skill stays with you: `git status`, `git diff --stat -- docs/project`.
2. Cut the doc areas **by file**: each area names the files or folders under `docs/project/` its
   doc-writer may change, no path in two areas (compared case-blind), `docs/README.md` in none. A
   folder ends in `/` or `/**`; without it the path counts as one file, and a doc-writer bound to a
   folder named that way can write nothing. The script refuses an overlap, since the check that
   compares parallel workers' write scopes does not see workflow agents. At most 12 areas per run;
   split a larger pass into two runs.
3. Start it: `Workflow` with `scriptPath` set to the absolute path of
   `.claude/skills/act-audit-docs/workflow.js` in the project root, and `args`:

   ```json
   {
     "date": "<today, YYYY-MM-DD>",
     "areas": [
       {"name": "architecture", "docs": ["docs/project/architecture.md"], "code": ["src/"], "focus": "optional"},
       {"name": "concepts", "docs": ["docs/project/concepts/"]}
     ],
     "wave": "optional: what the last feature wave changed",
     "readme": true
   }
   ```

   Per area an `explorer` (read-only, `Cap: 40`), then a `doc-writer` whose `Write scope:` is exactly
   that area's paths (`Cap: 40`); the areas run in parallel. A last `doc-writer` updates
   `docs/README.md` (`Cap: 15`), unless nothing changed or `readme` is `false`. The hooks hold each of
   them to its cap and write scope, as for any worker.
4. While it runs, start no other worker that writes under `docs/`.
5. The result lists per area `changed`, `corrections`, `code_findings` and `unverified`, plus
   `changed` for the whole run, the README step's own result as `readme` (`null` when it did not run),
   and the `skipped` areas that returned nothing. Check `git diff -- docs` against it: a code finding becomes a
   task, a skipped area gets an ordinary explorer → doc-writer pair or stays open. Record one outcome
   per agent (`usage.py --outcome explorer|doc-writer standard ...`, `R-role-outcome`), then the
   journal entry and `act-commit` as in the skill.
