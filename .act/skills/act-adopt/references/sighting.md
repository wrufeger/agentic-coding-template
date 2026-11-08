# Sighting hints (step 1)

Read from step 1 of `SKILL.md`. Read out to the owner every `-- … --` line the sighting prints (also `scan.json` under
`info`); none is a classification.

- `origin` (project made from the previous template): `template only` is nothing of the project's own;
  `own text: n lines` are lines the base text lacks; `unknown (base_commit not reachable)` cannot be told apart
  mechanically.
- `language hint: …` proposes the docs language for step 4.
- `possible home-made work system: …`: files named like a board or hand-over system. Ask the owner what they are (board,
  task list, journal, copy of an assistant's memory) and set the action from the answer: `legacy` (with
  `"confirmed": true` on an `unknown` row) keeps them in the archive, their open items become entries in step 6; plain
  documentation stays `keep`. Put the answer into the row's `note`.
- `foreign ids: …`: see `table-rules.md`.
- `predecessor leftover: git remote 'template' …`: left in place, a bare `git push`/`pull` goes to the template. Propose
  `git remote remove template` and do it only with the owner's yes; if the line says the branch has no other remote, the
  owner sets the project's own remote first.
