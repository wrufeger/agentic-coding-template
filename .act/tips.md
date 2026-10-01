# Tips

Fixed, English tip texts the SessionStart hook (`.act/hooks/checks/tips.py`) picks from — never
written by the model itself, so the wording stays stable and never invents a feature the project
does not actually have (`docs/ai/config.md` § Tips). Each tip is a `### TIP-<slug>` heading,
one `when:` line right under it, and one to two sentences of body text after that — that shape is
what `tips.py`'s parser reads, so keep new entries in the same form.

`when:` is one of: `always` · `config:<key>=<value>` (a `docs/ai/config.md` row) ·
`exists:<path>` / `missing:<path>` (repo-root-relative) · `unused:<key>` (never recorded by
`.act/scripts/usage.py`) · `older:<path>><n>m` (`<path>`'s last commit, or its mtime when it has
no commit history, is older than `<n>` months). `<path>` may list several candidates separated by
`|` (`older:package.json|composer.json>6m`): fires once at least one of them exists and every
existing one is old. A tip whose condition stops matching just drops out of the rotation — nothing
to clean up, and it comes back on its own if the situation changes again.

### TIP-review-before-accept
when: unused:reviewer
The `reviewer` sub-agent runs once per task before it gets accepted, adversarial by design — it
catches what a self-review misses. Worth asking for on a risky change, not only after something
already went wrong.

### TIP-act-deps
when: older:package.json|composer.json|requirements.txt|pyproject.toml|Gemfile|go.mod|Cargo.toml>6m
`act-deps` walks dependency updates one bundle (patch/minor) and one major at a time, checks green
after every step, and proposes the plan before touching anything.

### TIP-export-settings
when: unused:act-export-settings
`act-export-settings` writes this project's own rule deviations — and, if wanted, its scripts,
checklists, agents and skills — to a portable file: handy for carrying a setup into a new project,
or for checking what an export would reveal before sending it anywhere.

### TIP-load-settings
when: unused:act-load-settings
`act-load-settings` imports another project's exported settings file: mechanical checks sort
new/identical/dead on their own, real overlaps go to a model for judgment, and anything unresolved
lands in the inbox instead of being applied silently.

### TIP-feedback-on
when: config:feedback=off
Feedback to the template author is off right now — `act-feedback` (or a line starting
`feedback: <text>`) always sends a hand-written note regardless, but turning `feedback` on in
`config.md` also lets the project report rule/tool changes on its own, never anything about the
project itself.

### TIP-rules-list
when: always
`python .act/scripts/rules.py --list` prints the effective coding rules, one line per group with
its origin (template or local override); add `--area core` for the core/orchestrator rules
instead — faster than reading every rules file by hand.

### TIP-proposals
when: always
Anyone can drop a change proposal into `docs/ai/proposals/` (target: rules, coding, checklists or
config) without needing write access to the file itself — the owner reviews and integrates it.

### TIP-act-overview
when: always
`/act` lists every project skill with a one-line description, like a man page; `/act <name>` shows
one skill's instructions in full.

### TIP-doctor
when: unused:act-doctor
`act-doctor` (`.act/scripts/doctor.py`) reconciles the project against the template — stale
overrides, dead ids, orphaned bridges — worth a run after any template update.

### TIP-log-tail
when: config:logging=off
`python .act/scripts/log.py --tail` follows the live action log in a second terminal — useful for
a talk or demo where several workers run at once; turn `logging` on in `config.md` first.

### TIP-entries
when: unused:entries
`python .act/scripts/entries.py new <kind> <title...>` files a task/backlog/ledger/question entry
straight from the command line instead of writing the file by hand.

### TIP-idea
when: unused:act-idea
`act-idea` takes a feature request or change wish through options and a recommendation before any
code gets written — turns "can we add X" into a reviewed backlog item instead of a surprise diff.

### TIP-project-docs
when: missing:docs/project/architecture.md
`docs/project/architecture.md` is still missing — a short description of the project's structure
and data flow saves re-discovering it from the code every time.

### TIP-usage-show
when: exists:.act-local/usage.json
`python .act/scripts/usage.py --show` reports which roles, skills, scripts and checklists actually
get used — the same counter these tips read to know what you have already discovered yourself.
