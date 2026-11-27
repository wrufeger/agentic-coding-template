"""One reading of a shell command, shared by the checks of a single hook call.

The dispatcher builds one `Parse` per Bash or PowerShell call and hands it to every check as
payload["_act_parse"]. Each accessor calls the existing reader unchanged, the first time it is asked
and with the arguments it is asked with; later asks with the same arguments get a copy of the first
answer. No parsing logic lives here.

The git calls and the simple commands of a PowerShell call (`git_invocations`, `git_invocations_with_prefix`,
`commands`, `ps_calls`) are read from the PowerShell word lists (`ps_words`, read once) instead of the Bash reader,
which drops a backslash, reads a backtick as a command substitution and does not see a call inside `( )` or a script
block: a path keeps its backslash, a backtick continues the line or escapes one character, `--%` is not handed to git
(and the text behind it is still cut at `;` and `|`, which is stricter than PowerShell), `cmd /c` and `cmd /k` hand
the words behind them on as a call, `&` and the dot operator are taken off, and a call stands behind `{`, `(`, `$(`
and `@(`. The git calls of the Bash reading (`bash_calls_as_written`) come on top unless a PowerShell call is the same
call (the words compared with every backslash and backtick taken off, each PowerShell call standing for one Bash
call): they cover what a string hands to `iex` or `powershell -`, which the PowerShell reading does not read; a line
that does not tokenize falls back to the Bash reader. A git call behind `wsl` is one in both readings
(command_words._wsl_git_invocations). A Bash call reads as before.

Rules the accessors keep:
  * lazy: a reader runs only when a check asks for its result;
  * memoized per accessor and, for `write_targets`, `bash_write_targets`, `ps_words`, `inline_targets` and
    `inline_code`, per argument key (checks pass different working directories, git-write sets, flags and
    depths);
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


def _copy_invocations(found: list) -> list:
    """(prefix words, argv) pairs, both lists copied."""
    return [(list(prefix), list(args)) for prefix, args in found]


def _plain_words(words: list) -> list:
    """The words with every backslash and backtick taken off: how a call of the PowerShell reading and one of the
    Bash reading (which drops a backslash and reads a backtick as a substitution) are told to be the same call."""
    return [str(word).replace("\\", "").replace("`", "") for word in words]


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

    def for_text(self, text: str) -> "Parse":
        """This parse when it is the reading of `text`, else a fresh one of `text` for the same tool. A
        check that reads another text than the hook's command (the command with arithmetic, quoted heredocs,
        URL loop words or harmless inline code taken out, the whole text for an interpreter, or the command
        line a program hands to a shell) must not take it from the dispatcher's object."""
        return self if self._command == text else Parse(self._tool_name, text)

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
        """The argv of every git call: command_words._git_invocations(command) for a Bash call; for a PowerShell
        call the argv of git_invocations_with_prefix."""
        if self._tool_name == "PowerShell":
            return self._once(
                "git_invocations", lambda: [args for _prefix, args in self.git_invocations_with_prefix()],
                _copy_lists)
        return self._once(
            "git_invocations", lambda: _command_words._git_invocations(self._command), _copy_lists)

    def git_invocations_with_prefix(self) -> list:
        """(prefix words, git argv) pairs, both lists copied: command_words._git_invocations_with_prefix(command)
        for a Bash call. For a PowerShell call the git calls of the PowerShell reading (ps_calls): the Bash
        reader drops a backslash (a path like `..` + backslash + `proj` loses it), reads a backtick as a command
        substitution and a `(git ...)` or a script block as other words. The git calls of the Bash reading
        (bash_calls_as_written) come on top unless a PowerShell call is the same call; a line that does not
        tokenize (ps_words is empty) is read by the Bash reader as before."""
        if self._tool_name == "PowerShell":
            return self._once("git_invocations_with_prefix", self._read_powershell_git, _copy_invocations)
        return self._once(
            "git_invocations_with_prefix",
            lambda: _command_words._git_invocations_with_prefix(self._command),
            _copy_invocations)

    def _read_powershell_git(self) -> list:
        if not self.ps_words():
            return _command_words._git_invocations_with_prefix(self._command)
        found = _powershell_targets._ps_git_invocations(self.ps_calls())
        uncovered = [_plain_words(args) for _prefix, args in found]
        for prefix, call in self.bash_calls_as_written():
            name = _shell_targets._command_name(call[0])
            if name == "git":
                calls = [(prefix, call[1:])]
            elif name == "wsl":  # the git calls behind wsl in the Bash reading, like the PowerShell reading's own
                calls = _command_words._wsl_git_invocations([*prefix, call[0]], call[1:])
            else:
                continue
            for call_prefix, args in calls:
                plain = _plain_words(args)
                if plain in uncovered:
                    uncovered.remove(plain)  # a PowerShell call is the same call: it stands for this one, once
                else:
                    found.append((call_prefix, args))
        return found

    def bash_calls_as_written(self) -> list:
        """(prefix words, call) pairs of the Bash reading (words) of a PowerShell call, every simple command with its
        wrappers split off. The Bash reader sees what the PowerShell reader does not: the text a string or here-string
        hands to `iex` or `powershell -`, a line printed into a shell, a `find -exec`. Its git calls are added to the
        PowerShell reading of the git calls (git_invocations_with_prefix) unless a PowerShell call is the same call
        (same words once `\\` and a backtick are taken off, each PowerShell call standing for one); never added to the
        simple commands (commands) a directory change is read from."""
        return self._once("bash_calls_as_written", self._read_bash_calls_as_written, _copy_invocations)

    def _read_bash_calls_as_written(self) -> list:
        found = []
        for words, _separator in self.words():
            stripped = _command_words._strip_command_prefix(words)
            if stripped:
                found.append((words[:len(words) - len(stripped)], stripped))
        return found

    def ps_calls(self) -> list:
        """powershell_targets._ps_calls(ps_words): (prefix words, call) pairs for every call of a PowerShell
        command in the order they start: the call's command word first, the wrappers in front of it in the prefix;
        statements, calls inside `( )`, `$( )` and `{ }`, a call behind `&`, `.` or a variable assignment, the
        command lines of `cmd /c`, `bash -c` and `find -exec`. Meant for a PowerShell call."""
        return self._once("ps_calls", lambda: _powershell_targets._ps_calls(self.ps_words()), _copy_invocations)

    def commands(self) -> list:
        """The argv of every simple command, wrappers stripped, in order: stripped() for a Bash call and for a
        PowerShell line that does not tokenize; for a PowerShell call the calls of ps_calls (a backslash kept)."""
        if self._tool_name == "PowerShell":
            return self._once("commands", self._read_powershell_commands, _copy_lists)
        return self.stripped()

    def _read_powershell_commands(self) -> list:
        if not self.ps_words():
            return self.stripped()
        return [call for _prefix, call in self.ps_calls()]

    def assigned_git_invocations(self) -> list:
        """powershell_targets._assigned_git_invocations(ps_words): the git calls behind a PowerShell variable
        assignment, as (prefix words, git argv) pairs like git_invocations_with_prefix; empty for a command
        without one. Meant for a PowerShell call: the Bash word reader never sees these calls."""
        return self._once(
            "assigned_git_invocations",
            lambda: _powershell_targets._assigned_git_invocations(self.ps_words()), _copy_invocations)

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

    def inline_targets(self, base_cwd: str) -> list:
        """The path literals of inline interpreter code that holds a write call, as (path, directory it
        resolves against or None, language) triples: shell_targets._bash_inline_code_targets for a Bash call,
        powershell_targets._powershell_inline_code_targets for a PowerShell call. One reader call per
        working directory; a failure of the reader (inline_code.ReaderFailure) is replayed."""
        if self._tool_name == "PowerShell":
            return self._once(
                ("inline_targets", "PowerShell", base_cwd),
                lambda: _powershell_targets._powershell_inline_code_targets(self._command, base_cwd), list)
        return self._once(
            ("inline_targets", "Bash", base_cwd),
            lambda: _shell_targets._bash_inline_code_targets(self._command, base_cwd), list)

    def inline_code(self, base_cwd: Optional[str]) -> tuple:
        """shell_targets._bash_inline_code(command, base_cwd) whatever the tool: (the program texts a Bash
        command hands to an interpreter, the text their spans index into). One reader call per working
        directory (None = unknown is a key of its own)."""
        return self._once(
            ("inline_code", base_cwd), lambda: _shell_targets._bash_inline_code(self._command, base_cwd),
            lambda found: (list(found[0]), found[1]))

    def ps_raw_redirects(self) -> set:
        """powershell_targets._ps_raw_redirect_targets(command): the coarse operator-based reading of a
        PowerShell command the write-target reader could not evaluate."""
        return self._once(
            "ps_raw_redirects", lambda: _powershell_targets._ps_raw_redirect_targets(self._command), set)

    def plain_words(self) -> list:
        """command_words._command_word_lists(command, plain_only=True), the argv of every simple command: a
        command with a redirection once, without the operands of its redirections."""
        return self._once(
            "plain_words",
            lambda: [words for words, _sep in _command_words._command_word_lists(self._command, plain_only=True)],
            _copy_lists)
