#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Language server that makes entry ids such as T12, B7, Q3 or U5 clickable in Markdown files
#          opened in an editor (VS Code, IntelliJ with an LSP client). An id turns into a link, a
#          go-to-definition target and a hover card when an entry file for it exists under docs/ai/.
#          Read-only: it never writes, opens no network connection and starts no other program.
#          Stdlib only (plus actlib.py from its own folder), Python 3.9 or newer.
#
# Usage: started by the editor integration, speaking the Language Server Protocol over stdin/stdout
#        (Content-Length framed JSON-RPC); not meant to be run by hand.
#          python id_links_lsp.py            # serve until the client sends `exit` or closes stdin
#          python id_links_lsp.py --help     # print this description and exit
#
# Import rule: actlib.py is imported only from the folder this script lives in, never from the
#        project or the working directory. The editor integration installs both files side by side
#        in a per-user folder and starts the copy there, so a repository cannot swap the code.
#
# Search rules (every request searches afresh, nothing is stored on disk):
#   - id: ASCII-only regex \b[BQTU]\d+[a-z]?\b; a match counts only if an entry for it exists.
#   - project root: the workspace folder holding docs/ai/ that contains the document, else the first
#     folder upward from the document that holds docs/ai/; without a root there are no links.
#   - places, first hit wins: a single file `<ID>-*.md` or `<ID>.md` in docs/ai/inbox, docs/ai/work/tasks,
#     docs/ai/work/backlog; the same form in docs/ai/work/archive; then the archive collection files
#     (first line = collection mark), newest name first, section anchor `<a id="<ID>"></a>` followed by
#     `## <ID>` (or `## <ID> — <title>`), not inside a code fence. A file in the archive whose first
#     line is the collection mark is a collection whatever its name, never a single file.
#   - cost: per request the collection files are read once and indexed (canonical id -> section), so the
#     number of ids in a document does not multiply the reading.
#   - target: line 1 of a single file; the anchor line of a collection section (link target carries
#     a `#L<line>` fragment, definition carries the exact range).
#   - hover: `**<ID>** — <title>` (just `**<ID>**` without a title) and `Status: <status>`; status is the
#     whole value of the `status:` header field of a single file, else `open` (inbox, tasks, backlog) or
#     `archived` (archive, collection). Title and status are escaped, so no image or link comes out of them.
#   - link tooltip: the path of the target file relative to the project root, with `/`.
#
# Output format: LSP messages on stdout only. Diagnostics go to stderr as one line each, naming the
#        method and the exception type, never file contents. A failing request is answered with a
#        JSON-RPC error; the server keeps running. Exit code 0 after `shutdown` + `exit`, 1 after
#        `exit` without `shutdown`.

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, NamedTuple, Optional
from urllib.parse import unquote, urlparse

# Import actlib from this script's own folder only (see "Import rule" above).
sys.path.insert(0, str(Path(__file__).resolve().parent))
from actlib import (  # noqa: E402
    canonical_id, collection_sections, fence_step, header_block, is_collection, split_header,
)

ID_RE = re.compile(r"\b[BQTU]\d+[a-z]?\b", re.ASCII)
ENTRY_FILE_RE = re.compile(r"^([BQTU]\d+[a-z]?)(?:-.*)?\.md$", re.ASCII)
OPEN_DIRS = ("docs/ai/inbox", "docs/ai/work/tasks", "docs/ai/work/backlog")
ARCHIVE_DIR = "docs/ai/work/archive"
LINE_SPLIT_RE = re.compile(r"\r\n|\r|\n")
HEADING_RE = re.compile(r"^# +(\S.*?)\s*$")
MARKDOWN_SPECIAL_RE = re.compile(r"[\\`*_\[\]()<>!|~&]")
HEAD_READ_BYTES = 65536
MARK_PEEK_BYTES = 64
COLLECTION_READ_BYTES = 16 * 1024 * 1024
MAX_MESSAGE_BYTES = 64 * 1024 * 1024

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

CAPABILITIES = {
    "textDocumentSync": 1,
    "documentLinkProvider": {"resolveProvider": False},
    "definitionProvider": True,
    "hoverProvider": True,
}


class Entry(NamedTuple):
    """Where an id lives: the file, the 0-based line to jump to, and the facts for the hover card."""
    path: Path
    line: int  # 0-based
    title: str
    status: str
    collection: bool


def uri_to_path(uri: str) -> Path:
    """File URI to path, for POSIX (`file:///home/x`), Windows (`file:///D:/x`, `file:///d%3A/x`)
    and UNC (`file://host/share/x`) forms. Raises ValueError for any other scheme."""
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        raise ValueError(f"not a file URI (scheme {parsed.scheme!r})")
    path = unquote(parsed.path)
    if re.match(r"^/[A-Za-z]:", path):
        path = path[1:]
    elif parsed.netloc and parsed.netloc != "localhost":
        path = f"//{parsed.netloc}{path}"
    return Path(path)


def path_to_uri(path: Path) -> str:
    """Absolute path to a file URI (`file:///D:/x` on Windows, `file:///home/x` on POSIX)."""
    return path.resolve().as_uri()


def utf16_col(text: str, index: int) -> int:
    """UTF-16 code unit offset of the character index `index` (LSP positions count code units)."""
    return len(text[:index].encode("utf-16-le", "surrogatepass")) // 2


def char_index(text: str, col16: int) -> int:
    """Character index for a UTF-16 code unit offset."""
    units = 0
    for index, char in enumerate(text):
        if units >= col16:
            return index
        units += 2 if ord(char) > 0xFFFF else 1
    return len(text)


def read_text(path: Path, limit: int) -> str:
    """Up to `limit` bytes of `path` as UTF-8 text (undecodable bytes replaced); "" if unreadable."""
    try:
        with path.open("rb") as handle:
            return handle.read(limit).decode("utf-8", errors="replace")
    except OSError:
        return ""


def status_field(header: str) -> str:
    """The whole value of the first `status:` line of a header block, trimmed; "" if there is none or it
    is empty. Works line by line, so an empty value never reaches into the next field."""
    for line in header.split("\n"):
        if line.startswith("status:"):
            return line[len("status:"):].strip()
    return ""


def escape_markdown(text: str) -> str:
    """`text` with every Markdown-significant character backslash-escaped, so it shows as plain text
    (no image, link, emphasis or HTML out of an entry title). The JavaScript extension escapes the same set."""
    return MARKDOWN_SPECIAL_RE.sub(lambda match: "\\" + match.group(0), text)


def single_entry_facts(path: Path, default_status: str) -> tuple[str, str]:
    """(title, status) of a single entry file: the first `# ` heading outside a code fence, and the
    `status:` field read from the header block only."""
    text = read_text(path, HEAD_READ_BYTES)
    status = status_field(header_block(text)) or default_status
    title = ""
    fence = None
    for line in split_header(text)[1].split("\n"):
        line = line.rstrip("\r")
        fence = fence_step(fence, line)
        if fence is None and not title:
            heading = HEADING_RE.match(line)
            if heading:
                title = heading.group(1)
                break
    return title, status


SECTION_TITLE_RE = re.compile(r"^## \S+ — (.*)$")


def section_title(heading: str) -> str:
    """The text after `## <id> — ` of a collection section heading (the id may be written with
    leading zeros); "" if the heading has none."""
    match = SECTION_TITLE_RE.match(heading)
    return match.group(1).strip() if match else ""


class Finder:
    """One lookup session for one project root. Lives for a single request, so nothing it has seen
    is ever stale: each folder is listed once and the collection files are read and indexed once."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._names: dict[str, list[str]] = {}
        self._listing: dict[str, dict[str, list[Path]]] = {}
        self._marked: dict[Path, bool] = {}
        self._sections: Optional[dict[str, Entry]] = None

    def _file_names(self, rel: str) -> list[str]:
        """Names of the files in one folder, sorted."""
        if rel not in self._names:
            try:
                names = sorted(entry.name for entry in (self.root / rel).iterdir() if entry.is_file())
            except OSError:
                names = []
            self._names[rel] = names
        return self._names[rel]

    def _files(self, rel: str) -> dict[str, list[Path]]:
        """Entry files of one folder (names sorted), keyed by the id written in the file name."""
        if rel not in self._listing:
            found: dict[str, list[Path]] = {}
            folder = self.root / rel
            for name in self._file_names(rel):
                match = ENTRY_FILE_RE.match(name)
                if match:
                    found.setdefault(match.group(1), []).append(folder / name)
            self._listing[rel] = found
        return self._listing[rel]

    def _has_mark(self, path: Path) -> bool:
        """True if the file starts with the collection mark (only its first bytes are read)."""
        if path not in self._marked:
            self._marked[path] = is_collection(read_text(path, MARK_PEEK_BYTES))
        return self._marked[path]

    def _section_index(self) -> dict[str, Entry]:
        """Canonical id -> its section, over all archive collection files, newest name first (the first
        file to carry an id wins). Built on the first use in a request. A file counts by content: the
        collection mark in its first line makes it a collection, even if it is named like an entry."""
        if self._sections is None:
            index: dict[str, Entry] = {}
            folder = self.root / ARCHIVE_DIR
            for name in reversed(self._file_names(ARCHIVE_DIR)):
                if not name.endswith(".md"):
                    continue
                if ENTRY_FILE_RE.match(name) and not self._has_mark(folder / name):
                    continue
                text = read_text(folder / name, COLLECTION_READ_BYTES)
                if not is_collection(text):
                    continue
                lines = text.removeprefix("\ufeff").split("\n")
                for section_id, line_1based in collection_sections(text):
                    if section_id in index:
                        continue
                    heading = lines[line_1based].rstrip("\r") if line_1based < len(lines) else ""
                    index[section_id] = Entry(folder / name, line_1based - 1, section_title(heading),
                                              "archived", True)
            self._sections = index
        return self._sections

    def find(self, entry_id: str) -> Optional[Entry]:
        """The entry for `entry_id` in the documented order, or None."""
        for rel in OPEN_DIRS:
            for path in self._files(rel).get(entry_id, ()):
                return Entry(path, 0, *single_entry_facts(path, "open"), False)
        for path in self._files(ARCHIVE_DIR).get(entry_id, ()):
            if not self._has_mark(path):
                return Entry(path, 0, *single_entry_facts(path, "archived"), False)
        return self._section_index().get(canonical_id(entry_id))


def has_docs_ai(folder: Path) -> bool:
    try:
        return (folder / "docs" / "ai").is_dir()
    except OSError:
        return False


class Server:
    def __init__(self) -> None:
        self.documents: dict[str, str] = {}
        self.workspace: list[Path] = []
        self.shutdown_seen = False

    # -- project root and document text -------------------------------------------------------

    def root_for(self, uri: str) -> Optional[Path]:
        """The project root for a document: the workspace folder with docs/ai/ that contains it, else the
        first folder upward from the document that has docs/ai/, else None."""
        doc = uri_to_path(uri).resolve()
        for folder in self.workspace:
            try:
                doc.relative_to(folder)
            except ValueError:
                continue
            if has_docs_ai(folder):
                return folder
        for parent in doc.parents:
            if has_docs_ai(parent):
                return parent
        return None

    def text(self, uri: str) -> str:
        if uri in self.documents:
            return self.documents[uri]
        return read_text(uri_to_path(uri), COLLECTION_READ_BYTES)

    # -- capabilities --------------------------------------------------------------------------

    def document_links(self, uri: str) -> list[dict[str, Any]]:
        root = self.root_for(uri)
        if root is None:
            return []
        finder = Finder(root)
        cache: dict[str, Optional[Entry]] = {}
        links: list[dict[str, Any]] = []
        for line_no, line in enumerate(LINE_SPLIT_RE.split(self.text(uri))):
            for match in ID_RE.finditer(line):
                entry_id = match.group(0)
                if entry_id not in cache:
                    cache[entry_id] = finder.find(entry_id)
                entry = cache[entry_id]
                if entry is None:
                    continue
                target = path_to_uri(entry.path)
                if entry.collection:
                    target = f"{target}#L{entry.line + 1}"
                links.append({
                    "range": {
                        "start": {"line": line_no, "character": utf16_col(line, match.start())},
                        "end": {"line": line_no, "character": utf16_col(line, match.end())},
                    },
                    "target": target,
                    "tooltip": entry.path.relative_to(root).as_posix(),
                })
        return links

    def _entry_at(self, uri: str, position: dict[str, int]) -> Optional[tuple[str, Entry]]:
        root = self.root_for(uri)
        if root is None:
            return None
        lines = LINE_SPLIT_RE.split(self.text(uri))
        line_no = position["line"]
        if not 0 <= line_no < len(lines):
            return None
        line = lines[line_no]
        column = char_index(line, position["character"])
        for match in ID_RE.finditer(line):
            if match.start() <= column <= match.end():
                entry = Finder(root).find(match.group(0))
                return (match.group(0), entry) if entry is not None else None
        return None

    def definition(self, uri: str, position: dict[str, int]) -> Optional[dict[str, Any]]:
        hit = self._entry_at(uri, position)
        if hit is None:
            return None
        entry = hit[1]
        spot = {"line": entry.line, "character": 0}
        return {"uri": path_to_uri(entry.path), "range": {"start": spot, "end": spot}}

    def hover(self, uri: str, position: dict[str, int]) -> Optional[dict[str, Any]]:
        hit = self._entry_at(uri, position)
        if hit is None:
            return None
        entry_id, entry = hit
        title = f" — {escape_markdown(entry.title)}" if entry.title else ""
        value = f"**{entry_id}**{title}\n\nStatus: {escape_markdown(entry.status)}"
        return {"contents": {"kind": "markdown", "value": value}}

    # -- protocol ------------------------------------------------------------------------------

    def initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        uris = [folder["uri"] for folder in (params.get("workspaceFolders") or [])]
        if not uris and params.get("rootUri"):
            uris = [params["rootUri"]]
        self.workspace = []
        for uri in uris:
            try:
                self.workspace.append(uri_to_path(uri).resolve())
            except (ValueError, OSError) as error:
                log(f"initialize: workspace folder ignored ({type(error).__name__})")
        return {"capabilities": CAPABILITIES, "serverInfo": {"name": "act-id-links", "version": "1"}}

    def dispatch(self, method: str, params: dict[str, Any]) -> Any:
        """Result of a request, or None for a notification; raises for a bad request."""
        if method == "initialize":
            return self.initialize(params)
        if method == "shutdown":
            self.shutdown_seen = True
            return None
        if method == "textDocument/didOpen":
            document = params["textDocument"]
            self.documents[document["uri"]] = document["text"]
        elif method == "textDocument/didChange":
            changes = params.get("contentChanges") or []
            if changes:
                self.documents[params["textDocument"]["uri"]] = changes[-1]["text"]
        elif method == "textDocument/didClose":
            self.documents.pop(params["textDocument"]["uri"], None)
        elif method == "textDocument/documentLink":
            return self.document_links(params["textDocument"]["uri"])
        elif method == "textDocument/definition":
            return self.definition(params["textDocument"]["uri"], params["position"])
        elif method == "textDocument/hover":
            return self.hover(params["textDocument"]["uri"], params["position"])
        return None

    def handle(self, message: dict[str, Any]) -> Optional[dict[str, Any]]:
        """The reply for one message, or None (notification, response from the client)."""
        method = message.get("method")
        request_id = message.get("id")
        is_request = "id" in message and method is not None
        if method == "exit":
            sys.exit(0 if self.shutdown_seen else 1)
        if not isinstance(method, str):
            return None
        if is_request and self.shutdown_seen and method != "shutdown":
            return error_reply(request_id, INVALID_REQUEST, "server is shutting down")
        if is_request and method not in KNOWN_REQUESTS:
            return error_reply(request_id, METHOD_NOT_FOUND, f"method not found: {method}")
        if not is_request and method not in KNOWN_NOTIFICATIONS:
            return None  # an unknown notification is ignored
        params = message.get("params") or {}
        try:
            if not isinstance(params, dict):
                raise TypeError("params is not an object")
            result = self.dispatch(method, params)
        except (KeyError, TypeError, ValueError, AttributeError, IndexError) as error:
            log(f"{method}: invalid params ({type(error).__name__})")
            return error_reply(request_id, INVALID_PARAMS, f"invalid params for {method}") if is_request else None
        except OSError as error:
            log(f"{method}: failed ({type(error).__name__})")
            return error_reply(request_id, INTERNAL_ERROR, f"{method} failed") if is_request else None
        return {"jsonrpc": "2.0", "id": request_id, "result": result} if is_request else None


KNOWN_REQUESTS = frozenset({"initialize", "shutdown", "textDocument/documentLink", "textDocument/definition",
                            "textDocument/hover"})
KNOWN_NOTIFICATIONS = frozenset({"textDocument/didOpen", "textDocument/didChange", "textDocument/didClose"})


def log(text: str) -> None:
    """One diagnostic line on stderr (never file contents)."""
    print(f"id-links: {text}", file=sys.stderr, flush=True)


def error_reply(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def read_message(stream: Any) -> Optional[dict[str, Any]]:
    """Next framed message from a binary stream; None at end of input. A malformed frame raises
    ValueError after its bytes are consumed, so the caller can answer and go on."""
    length: Optional[int] = None
    while True:
        line = stream.readline()
        if not line:
            return None
        line = line.strip()
        if not line:
            if length is None:
                continue  # stray blank line before any header
            break
        name, _, value = line.partition(b":")
        if name.strip().lower() == b"content-length":
            length = int(value)  # ValueError on garbage
    if not 0 <= length <= MAX_MESSAGE_BYTES:
        raise ValueError("content length out of range")
    body = stream.read(length)
    if len(body) < length:
        return None
    parsed = json.loads(body.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError("message is not an object")
    return parsed


def write_message(stream: Any, message: dict[str, Any]) -> None:
    body = json.dumps(message, ensure_ascii=False).encode("utf-8")
    stream.write(b"Content-Length: %d\r\n\r\n" % len(body) + body)
    stream.flush()


def serve() -> int:
    server = Server()
    stdin, stdout = sys.stdin.buffer, sys.stdout.buffer
    while True:
        try:
            message = read_message(stdin)
        except (ValueError, UnicodeDecodeError) as error:
            log(f"unreadable message ({type(error).__name__})")
            write_message(stdout, error_reply(None, PARSE_ERROR, "parse error"))
            continue
        if message is None:
            return 0
        try:
            reply = server.handle(message)
        except Exception as error:  # noqa: BLE001 - last line of defence: one request must not end the server
            log(f"{message.get('method')}: internal error ({type(error).__name__})")
            reply = error_reply(message.get("id"), INTERNAL_ERROR, "internal error") if "id" in message else None
        if reply is not None:
            write_message(stdout, reply)


def main() -> int:
    # Output can carry an em dash; on Windows, stdout/stderr otherwise default to the console's
    # legacy code page instead of UTF-8. Same fix as the other scripts in this folder.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(
        description="Language server (stdio) that turns entry ids such as T12 in Markdown files into links, "
                    "go-to-definition targets and hover cards for the matching entry under docs/ai/. "
                    "Read-only, no network. Started by an editor integration; without arguments it serves "
                    "the Language Server Protocol on stdin/stdout.")
    parser.parse_args()
    return serve()


if __name__ == "__main__":
    sys.exit(main())
