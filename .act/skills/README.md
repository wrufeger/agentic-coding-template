# Skills

One directory per skill, named after the skill: `.act/skills/<name>/SKILL.md`, plus any other
file the skill needs in the same directory (references, scripts, templates). `SKILL.md` starts
with YAML frontmatter — `name`, `description` — following the open Agent Skills format; the body
below the frontmatter is the skill's instructions, written tool-neutral.

A skill may carry `reasoning: <level>` (a value of `reasoning_scale` in `.act/tiers.json`: `none`, `low`,
`medium`, `high`, `xhigh`, `max`) to ask for that thinking level while it runs. The project copy for a tool
with a researched mapping (`reasoning_field` in `tiers.json`, Claude Code: `effort`) gets that field in place
of the `reasoning` line; the `.agents/skills/` mirror stays verbatim, and a skill without the key inherits the
session. A row naming the skill in `docs/ai/config.md` § Roles overrides the level for one project.

`.act/scripts/init.py`'s `copy_targets()` turns every directory here into a project copy: the
whole directory, file for file, under `.claude/skills/<name>/` (only when `claude-code` is one of
the project's configured tools, `docs/ai/config.md` § Project) and under `.agents/skills/<name>/`
— the tool-neutral mirror read by Codex, Copilot, Gemini CLI and Cursor — once any one of those is
configured. Where a project's file lands is data (`SKILL_TARGET_DIRS` in `init.py`), one entry per
skills folder with its tool gate, so a further tool that reads `.agents/skills/` needs only its id
added to that gate, and a further tool with its own skills folder needs one more line there and
nothing else; adding a skill itself needs no change anywhere — `copy_targets()` enumerates this
directory at call time.

A project copy is a template-owned copy, not a bridge: `.act/scripts/update.py` replaces it on
update if it is still byte-identical to what was last generated (tracked as a hash per file in
`.act-lock.json` § `copies`), keeps it and reports if the project edited it, leaves it deleted if
the project removed it, and creates it if the skill is new since the last update. A project
override at `docs/ai/local/skills/<name>/<file>` wins over the matching file here (`actlib.resolve()`,
the same rule as everywhere else in this template) — the project copy is then generated from the
override, not from this source.

A project's own skill — `docs/ai/local/skills/<name>/` with no counterpart here — gets the same copies:
`act-load-settings` writes them when it imports the skill, and one created by hand gets them at the next
session start or `update.py` run (`.act/scripts/unit_copies.py`), recorded in `.act-lock.json` § `copies`
like a template copy. An own role under `docs/ai/local/agents/` gets its bridge the same way.

## Writing a skill description

The description is all an agent sees of a skill until it decides to load it, and an agent that reads a
summary of the steps acts on the summary instead of loading the skill. So the description names the
trigger, not the procedure:

1. Start with the trigger: "Use when ..." (or "Use to / after / before / for ..."), naming concrete
   situations and typical user phrasings.
2. At most one short sentence on the outcome; never a list of steps.
3. Optionally "Not for X — use act-Y." to separate neighbouring skills.
4. English, 15–55 words (`skills.py --check` warns above 55, errors above 65 or below 15).

`python .act/scripts/skills.py --check` lints every skill against this (and `doctor.py` reports the
project's own skills); it also counts all descriptions together, since they are loaded into every session.

Two habits keep skill and rule text short. Deletion test: cut a line; if the agent's behaviour would not
change, it stays cut. Progressive disclosure: keep `SKILL.md` to the core flow (about 300 lines at most)
and put detail in `references/<topic>.md`, with a pointer in `SKILL.md` saying when to read it.
