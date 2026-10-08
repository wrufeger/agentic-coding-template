# A file that stays open (step 7)

Read from step 7 of `SKILL.md` when `apply` left a file in `.act-local/import/`.

A file `apply` could not fully resolve stays in `.act-local/import/` and prints, per item, why:
   declined by you, needs `--yes`, needs a judgment (content overlap), a name/id collision, or
   rejected (risky frontmatter, shadowing, a bad path, ...) — plus how many items from that file
   already applied. Put that in your own words for the human (why it is stuck, not just the raw
   line) and ask for one of the four decisions:
   - **keep** (offered again next run) — the safe default when nothing is actually wrong, just
     `--yes`/a judgment is still missing and the human wants to supply it later. Suggest a plain
     rerun with `--yes`/`--judgments` only when that could actually resolve it — a name/id
     collision or a rejected bundled file needs `partial`/`ignore`/`delete` instead, a rerun
     reproduces the exact same outcome.
   - **partial** — close it now, keep what applied, discard the rest. Suggest this when the open
     items are things that will not resolve themselves (a genuine content collision, an import the
     human has decided against for part of the file).
   - **ignore** — never offer this file again; for a file the human wants gone from view entirely.
   - **delete** — remove the file outright. Only pass this after the human has explicitly said so
     in this conversation — never infer it from "clean it up" or similar.
   Call `python .act/scripts/settings_load.py apply --resolve <file>=<action>` with the decision
   (repeatable for several files in one call). **`--resolve` is a pure filing run, not a second
   `apply`:** as soon as it is given, every file in `.act-local/import/` other than the one(s)
   named — including one dropped in since the last `apply` — is left completely alone, and even a
   named file only gets the action asked for, nothing from it is written/applied. There is no TTY
   prompt in this mode either. `partial` still needs to know what it is discarding, so for that one
   action the file is read again — but only read, never applied — to list what stays open; a file
   that fails to load cannot be given `partial` at all (nothing to list), only `keep`/`ignore`/
   `delete`.
