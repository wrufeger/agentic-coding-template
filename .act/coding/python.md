# Coding rules — Python

summary: strict annotations, stdlib-first, data models, module layout, toolchain, tests

Rules for Python 3 with type annotations, a stdlib-first preference and automated linting. Group IDs
(`CR-python-<name>`) are stable and never reassigned; a group whose purpose no longer holds gets a new ID
and is listed as `retired:` in this header.

## `CR-python-basics` — Established Python defaults

summary: annotations, f-strings, context managers, exception handling, venv, lint

- Annotate every function signature (parameters and return value), including internal/private functions.
- Use f-strings, not `%` formatting or `.format()`.
- Use `with` for anything that must be opened and closed (files, locks, connections).
- Never use a mutable default argument (`def f(x: list = [])`) — default to `None` and initialize inside
  the function body.
- Catch specific exception types; never a bare `except Exception` without re-raising or logging it. Every
  raised or logged error states what failed and with what value — a caller or log reader must find the
  cause without opening the source.
- Use `is`/`is not` only for identity comparisons (`None`, singletons), never for values.
- One virtual environment (`venv`) per project, dependencies pinned in a lockfile (`requirements.txt`,
  `poetry.lock`); never a global install of project dependencies.
- Lint is the stack's standard and belongs in the project; run what is installed, install nothing unasked.

## `CR-python-stdlib-first` — Standard library before a new dependency

summary: reach for the stdlib before adding a package

- Prefer the standard library over adding an external dependency; add one only where the stdlib genuinely
  falls short.

## `CR-python-data-models` — Typed data instead of loose dicts

summary: dataclasses, TypedDict or pydantic for structured data

- Model structured data with `dataclasses`, `TypedDict` or `pydantic`, not a loose `dict`.

## `CR-python-module-structure` — One module per responsibility

summary: module boundaries, no circular imports

- One module per functional responsibility, no catch-all module without a clear boundary.
- Resolve circular imports by fixing the module boundaries, not by working around them with deferred or
  local imports.

## `CR-python-toolchain` — Lint and format tooling

summary: ruff for lint and formatting

- `ruff` for both linting and formatting, configured in the project; `black` remains a common alternative
  for formatting in existing projects.

## `CR-python-tests` — Unit tests

summary: pytest with fixtures

- `pytest`, with fixtures instead of repeating setup code in every test module.
