"""One reading of a shell command, shared by the checks of a single hook call.

The dispatcher builds one `Parse` per Bash or PowerShell call and hands it to every check as
payload["_act_parse"]. Each accessor calls the existing reader unchanged, the first time it is asked
and with the arguments it is asked with; later asks with the same arguments get a copy of the first
answer. No parsing logic lives here.

Rules the accessors keep:
  * lazy: a reader runs only when a check asks for its result;
  * memoized per accessor and, for `write_targets`, `bash_write_targets` and `ps_words`, per argument
    key (checks pass different working directories, git-write sets, flags and depths);
  * a reader that raises has its exception stored and the same exception re-raised on every later ask,
    the reader not called again, so its type stays (the dispatcher recognizes `inline_code.ReaderFailure`);
  * every result is returned as a fresh copy, so one check cannot change what the next one sees;
  * nothing time-dependent is kept: the commit scans' git alias lookups run under each check's own
    deadline and stay with the check, only the pure token stream (`chain_tokens`) is shared;
  * only these top-level reader calls are memoized, never the scanners' nested calls: the rsync
    variable-name flag in shell_targets is a module global set and restored around each top-level call.

Imports are deliberately one-way: this module imports the readers, no reader imports this module.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from . import command_words as _command_words
from . import powershell_targets as _powershell_targets
from . import shell_targets as _shell_targets


def _copy_pairs(pairs: list) -> list:
    """(argv, separator) pairs, argv lists copied."""
    return [(list(words), sep) for words, sep in pairs]


def _copy_lists(lists: list) -> list:
    return [list(words) for words in lists]


def parse_for(payload: dict, command: str) -> "Parse":
    """The dispatcher's parse of this call when payload["_act_parse"] is a Parse of the same command and
    tool, else a fresh one: a check called outside the dispatcher or on another event reads as before."""
    tool_name = payload.get("tool_name")
    shared = payload.get("_act_parse")
    if isinstance(shared, Parse) and shared.command == command and shared.tool_name == tool_name:
        return shared
    return Parse(tool_name, command)


class Parse:
    """The reading of one command for one tool call. Read-only: no public setters."""

    __slots__ = ("_tool_name", "_command", "_memo")

    def __init__(self, tool_name: str, command: str) -> None:
        if not isinstance(command, str):
            raise TypeError(f"Parse needs a str command, got {type(command).__name__}")
        self._tool_name = tool_name
        self._command = command
        self._memo: dict[Any, tuple[bool, Any]] = {}  # key -> (ok, value or exception)

    @property
    def tool_name(self) -> str:
        return self._tool_name

    @property
    def command(self) -> str:
        return self._command

    def _once(self, key: Any, reader: Callable[[], Any], copy: Callable[[Any], Any]) -> Any:
        """Run `reader` on the first ask for `key`; later asks replay its outcome."""
        if key not in self._memo:
            try:
                self._memo[key] = (True, reader())
            except Exception as exc:  # noqa: BLE001 - stored and re-raised unchanged on every ask
                self._memo[key] = (False, exc)
        ok, value = self._memo[key]
        if not ok:
            raise value
        return copy(value)

    def words(self) -> list:
        """command_words._command_word_lists(command): (argv, preceding separator) pairs."""
        return self._once("words", lambda: _command_words._command_word_lists(self._command), _copy_pairs)

    def stripped(self) -> list:
        """command_words._stripped_word_lists(command)."""
        return self._once("stripped", lambda: _command_words._stripped_word_lists(self._command), _copy_lists)

    def ps_words(self, depth: int = 0) -> list:
        """powershell_targets._ps_word_lists(command, depth): the word lists read with PowerShell's own
        tokenizer, at depth 0 the text behind a nested `pwsh -Command` included, at depth 2 the command
        line only; empty when the line does not tokenize (a result, not an error). One reader call per
        depth; nested calls read their own text and are not kept here."""
        if depth == 0:
            return self._once(
                "ps_words", lambda: _powershell_targets._ps_word_lists(self._command), _copy_lists)
        return self._once(
            ("ps_words", depth), lambda: _powershell_targets._ps_word_lists(self._command, depth), _copy_lists)

    def git_invocations(self) -> list:
        """command_words._git_invocations(command)."""
        return self._once(
            "git_invocations", lambda: _command_words._git_invocations(self._command), _copy_lists)

    def git_invocations_with_prefix(self) -> list:
        """command_words._git_invocations_with_prefix(command): (prefix words, git argv) pairs, both lists
        copied."""
        return self._once(
            "git_invocations_with_prefix",
            lambda: _command_words._git_invocations_with_prefix(self._command),
            lambda found: [(list(prefix), list(args)) for prefix, args in found])

    def chain_tokens(self) -> Optional[list]:
        """shell_targets._tokenize_chain(command): the token stream of the whole command, or None when
        it does not tokenize (a result, not an error). Only this pure reading is shared by the commit
        scans; their alias lookups run under each check's own deadline and are never kept here.

        The copy is a list copy: the tokens are (text, is_operator) tuples whose text is a str or a
        `_Word`; no reader assigns to a token or its word (the `_Word` attributes are set in the
        tokenizer before it returns)."""
        return self._once(
            "chain_tokens", lambda: _shell_targets._tokenize_chain(self._command),
            lambda found: None if found is None else list(found))

    def write_targets(
        self, base_cwd: Optional[str], git_writes: frozenset, inline: bool = True, broad: bool = False,
    ) -> Optional[Any]:
        """The write targets of the command for this tool: a list for Bash (_bash_write_targets), a set
        or None for PowerShell (_powershell_write_targets). One reader call per argument key."""
        git_writes = frozenset(git_writes)
        if self._tool_name == "PowerShell":
            key = ("write_targets", "PowerShell", base_cwd, git_writes, bool(broad))

            def read_ps() -> Any:
                return _powershell_targets._powershell_write_targets(
                    self._command, base_cwd, git_writes, broad=broad)

            return self._once(key, read_ps, lambda found: None if found is None else set(found))
        return self.bash_write_targets(base_cwd, git_writes, inline)

    def bash_write_targets(self, base_cwd: Optional[str], git_writes: frozenset, inline: bool = True) -> list:
        """The Bash reading of the write targets whatever the tool: for a PowerShell call it is the reading
        of the native programs the command starts, asked on top of write_targets. Its key names the Bash
        reader, so it never meets a PowerShell key; a Bash call's write_targets is this same call."""
        git_writes = frozenset(git_writes)
        key = ("write_targets", "Bash", base_cwd, git_writes, bool(inline))

        def read_bash() -> Any:
            return _shell_targets._bash_write_targets(self._command, base_cwd, git_writes, inline)

        return self._once(key, read_bash, list)
