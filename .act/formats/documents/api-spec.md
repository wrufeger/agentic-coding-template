# API spec scaffold

summary: the interface other code calls — what goes in, what comes out, what can go wrong

Copy the block into `docs/project/api.md`, once per endpoint, command or public function; keep the order of the
code. The spec describes what the code does today, checked against the code (`act-audit-docs`), not what is
planned.

```markdown
## <METHOD> <path> | <command> | <function signature>

- **Purpose:** <one sentence>
- **Auth:** <none | token | session | role> — <where it is checked>
- **Input:** <parameter — type — required? — meaning, one line each>
- **Output:** <status or return type — shape in a few lines, with one example>
- **Errors:** <status or exception — when — what the caller can do>
- **Notes:** <idempotent? rate limit? pagination? deprecation date?>
```

Start with a short overview above the first entry: base URL or entry point, versioning, content type, how errors
look in general.
