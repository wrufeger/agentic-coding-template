"""Shell brace expansion (`{a,b}`) shared by the checks that must read a word the way the shell will.

`expand_braces` is the lenient reader secret-read uses (it only needs the names a word can turn
into); `literal_brace_variants` is the strict one the write-scope check uses: it answers only for a
plain literal list and otherwise says "not knowable" so the caller keeps treating the word as dynamic.
"""
from __future__ import annotations

import re
from typing import Optional

__all__ = ["BRACE_RE", "MAX_BRACE_RESULTS", "expand_braces", "literal_brace_variants"]

# One innermost group `{...}` without further braces in it.
BRACE_RE = re.compile(r"\{([^{}]*)\}")
MAX_BRACE_RESULTS = 64
# What makes a word dynamic besides a brace group: a variable or command substitution, a backtick
# span, a leading `~`.
_OTHER_EXPANSION_RE = re.compile(r"[$`]|^~")


def expand_braces(pattern: str) -> list[str]:
    """`pattern` with its non-nested `{a,b}` groups expanded (`.env{,.local}` -> `.env`,
    `.env.local`); at most 64 results, the rest is dropped."""
    results = [pattern]
    for _ in range(8):
        next_results: list[str] = []
        changed = False
        for item in results:
            match = BRACE_RE.search(item)
            if not match:
                next_results.append(item)
                continue
            changed = True
            for option in match.group(1).split(","):
                next_results.append(item[:match.start()] + option + item[match.end():])
        results = next_results[:MAX_BRACE_RESULTS]
        if not changed:
            break
    return results


def literal_brace_variants(word: str, live: Optional[str]) -> Optional[list[str]]:
    """The words a literal brace list in `word` expands to, or None when `word` is not exactly that:
    it has no brace group, a `$`/backtick/leading `~` (the shell expands more than the list), a
    nested or unbalanced brace, a group without a comma (`{a}` and `{1..3}` are not lists), or the
    expansion would exceed 64 results. `live` says which characters of `word` the shell still acts
    on (`shell_targets._Word.live`: "L" unquoted and unescaped, "." quoted or escaped): every brace
    and comma must be live, since the shell never expands a quoted or escaped one, and without that
    knowledge (`live` None, or not as long as `word`) nothing is known and the answer is None."""
    if live is None or len(live) != len(word):
        return None
    if "{" not in word and "}" not in word:
        return None
    if _OTHER_EXPANSION_RE.search(word):
        return None
    if any(char in "{}," and mark != "L" for char, mark in zip(word, live)):
        return None
    depth = 0
    for char in word:
        if char == "{":
            depth += 1
            if depth > 1:
                return None
        elif char == "}":
            depth -= 1
            if depth < 0:
                return None
    if depth != 0:
        return None
    groups = BRACE_RE.findall(word)
    if not groups or any("," not in group for group in groups):
        return None
    count = 1
    for group in groups:
        count *= len(group.split(","))
        if count > MAX_BRACE_RESULTS:
            return None
    variants = expand_braces(word)
    if len(variants) != count or any("{" in variant or "}" in variant for variant in variants):
        return None
    return variants
