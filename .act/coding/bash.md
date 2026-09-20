# Coding rules — Bash

summary: strict mode, quoting, exit codes, error messages, shellcheck, pitfalls

Rules for Bash scripts. Group IDs (`CR-bash-<name>`) are stable and never reassigned; a group
whose purpose no longer holds gets a new ID and is listed as `retired:` in this header.

## `CR-bash-basics` — Strict mode, quoting, error handling, shellcheck

summary: set -euo pipefail, quoting, deliberate exit codes, errors on stderr, shellcheck, pitfalls

- Start every script with `set -euo pipefail` as the first executable line.
- Quote variables consistently (`"$var"`), especially paths that may contain spaces.
- Set exit codes deliberately (`exit 0`/`exit 1`/specific codes) instead of letting the last
  command's status pass through implicitly.
- Check arguments and inputs before use (count, whether a path exists); report failures on stderr,
  and name what failed and with what — not a bare "error".
- Run `shellcheck` as the stack's standard linter before every commit; do not suppress its
  warnings wholesale.
- Pitfalls:
  - Never parse the output of `ls` in a loop — use globbing or `find ... -print0` with
    `read -d ''`.
  - Check the result of `cd` (`cd dir || exit 1`); otherwise following commands run in the
    wrong directory.

## `CR-bash-script-shape` — One script, one purpose

summary: header comment, functions over duplication, single-purpose scripts

- Start with a header comment stating purpose, an example call, and the expected output/exit
  behavior.
- Use functions for reusable sections instead of copying the same command sequence.
- One script, one clearly named purpose — no multi-purpose script with mode flags for
  unrelated tasks.
