#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Moves each ideas file in docs/ai/concept/ unchanged to docs/ai/whiteboard-<identity>.md, turns each
#          proposal in docs/ai/proposals/ into an inbox question quoting its text, retires both folders.
#          What this does (read and written as bytes where it edits a file, so encoding, BOM and line
#          endings stay as they were):
#            1. docs/ai/README.md, the rules for the whiteboards, is created when it is missing (from
#               docs/ai/local/skeleton/README.md when the project has its own, else .act/skeleton/README.md).
#            2. Every docs/ai/concept/ideas-<identity>.md moves unchanged to docs/ai/whiteboard-<identity>.md. A name
#               that is taken stays where it is and is named. A picture or other file beside it goes to docs/ai/
#               along with an ideas file that moves and links it (a link that resolves to the file, as
#               entries.linked_local_files finds it); it stays, and is named, when an ideas file that stays or any
#               other Markdown file below docs/ (not the journal) links it too. What the session start recorded as
#               processed per file (.act-local/whiteboard-seen.json, else .act-local/ideas-seen.json) carries over
#               by itself.
#            3. Every other Markdown file directly in docs/ai/concept/ (a concept page) moves to
#               docs/project/concepts/ through move_doc.py, which pulls its links and paths along; a name taken
#               there stays and is named. A line for concepts/ goes into docs/project/README.md when it has none.
#               The path of a moved ideas file (docs/ai/concept/ideas-<identity>.md) written in the Markdown files
#               below docs/ (not the journal) and the link to it in a concept page (moved, or left because its name
#               is taken) follow it. A whiteboard (moved or already there) and an ideas file left in place keep every
#               byte: neither the path rewrite nor move_doc.py changes them; one that links or names a moved concept
#               page (by link or by written path) is named.
#            4. Every Markdown file in docs/ai/proposals/ except its README.md becomes one inbox question
#               (adopt_entries.proposal_question: target and author named, the old text quoted, take it over or leave
#               it out) and moves to docs/ai/work/archive/proposals/. A file that cannot be read as UTF-8, or whose
#               name is taken in the archive, stays and is named. When filing stops halfway, the questions already
#               written stay (their proposals move on, their files are listed as touched), the others stay and
#               are named.
#            5. The README.md of both folders goes through `entries.py archive` (as concept-README.md and
#               proposals-README.md); the folders go when they are empty, else what is left is named.
#            6. docs/README.md: the two rows the template wrote for docs/ai/concept/ and for
#               docs/ai/inbox/ + docs/ai/proposals/ are replaced by the rows of .act/bridges/docs-readme.md when
#               they stand word for word as the template wrote them (the date column aside); a changed row stays and
#               is named.
#          The way back is the update's own commit: `git revert <that commit>` restores every moved, archived and
#          changed file and the old .act/; nothing is rewritten in place except the two rows of docs/README.md and the
#          links of a moved concept page, so a hand-made way back is `git checkout <commit before the update> --
#          docs/ai docs/README.md` plus removing what the migration added. Nothing found: nothing to do, and the
#          description says so.
#          A file or folder on the way that is a symbolic link or a Windows junction is never touched: the
#          description names it. plan() only reads; apply() reports what it did. A second run finds nothing.
#
# Contract (.act/scripts/update.py step 8): plan(root) -> str, apply(root) -> (str, list[str]) of project-relative
# paths (posix separators) touched, deleted and created ones alike (the update commits by those paths). Stdlib
# only; the link test lives in the sibling file _links.py (loaded below, shipped together with this file); the
# scripts of the project's own .act/ are run as programs of their own (move_doc.py, entries.py, adopt_entries.py), so
# the modules this run already loaded are never mixed with their new versions.

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
from datetime import date
from pathlib import Path


def _load_links():
    """The sibling _links.py (link test), loaded by file name."""
    spec = importlib.util.spec_from_file_location("_act_migration_links", Path(__file__).with_name("_links.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_LINKS = _load_links()

CONCEPT = "docs/ai/concept"
PROPOSALS = "docs/ai/proposals"
WHITEBOARD_DIR = "docs/ai"
CONCEPTS_NEW = "docs/project/concepts"
PROPOSALS_ARCHIVE = "docs/ai/work/archive/proposals"
DOCS_README = "docs/README.md"
BRIDGE = ".act/bridges/docs-readme.md"
SHOWN_MAX = 6
# The two rows of docs/README.md the template wrote before (cells without the date column), and the first cell of the
# row of .act/bridges/docs-readme.md that replaces each.
OLD_ROWS = (
    ("`docs/ai/concept/`",
     "One ideas file per person (`ideas-<identity>.md`): your own ideas and concept notes, picked up at the next "
     "session start",
     "whenever you have an idea; the assistant when the session start names new entries",
     "`docs/ai/whiteboard-<identity>.md`"),
    ("`docs/ai/inbox/`, `docs/ai/proposals/`",
     "Things waiting for a decision: questions, tasks for a human, tool reports, notes, proposed rule changes",
     "at session start, and before starting a new task",
     "`docs/ai/inbox/`"),
)
# Run in a fresh interpreter inside the project: files each proposal of a JSON list on stdin as an inbox question with
# the text adopt_entries.proposal_question builds; prints one JSON line (the new path) per question as soon as it is
# written, so a failure halfway still tells which ones were filed.
_FILE_QUESTIONS = (
    "import json, os, sys\n"
    "from pathlib import Path\n"
    "sys.path.insert(0, sys.argv[2])\n"
    "import adopt_entries, entries\n"
    "root = Path(sys.argv[1])\n"
    "items = json.loads(sys.stdin.buffer.read().decode('utf-8'))\n"
    "for item in items:\n"
    "    title, body = adopt_entries.proposal_question(root, item)\n"
    "    path, _ = entries.create_entry(root, 'question', title, body=body, answer_block=True)\n"
    "    print(json.dumps(Path(os.path.relpath(path, root)).as_posix()), flush=True)\n"
)
# Run in a fresh interpreter inside the project: reads a JSON list of project-relative Markdown paths on stdin, prints
# a JSON object {path: [project-relative files it links by a link that resolves to an existing file]} (entries.py's
# own link test, the one the orphan scan of doctor.py uses).
_LINKED_FILES = (
    "import json, os, sys\n"
    "from pathlib import Path\n"
    "sys.path.insert(0, sys.argv[2])\n"
    "import entries\n"
    "root = Path(sys.argv[1])\n"
    "out = {}\n"
    "for rel in json.loads(sys.stdin.buffer.read().decode('utf-8')):\n"
    "    try:\n"
    "        text = (root / rel).read_bytes().decode('utf-8')\n"
    "    except (OSError, UnicodeDecodeError):\n"
    "        continue\n"
    "    found = entries.linked_local_files(text, (root / rel).parent)\n"
    "    out[rel] = sorted(Path(os.path.relpath(path, root)).as_posix() for path in found)\n"
    "print(json.dumps(out))\n"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _run(root: Path, script: str, *args: str) -> subprocess.CompletedProcess:
    """A script of the project's own .act/scripts/ as a program of its own, run from the project root."""
    return subprocess.run([sys.executable, str(root / ".act" / "scripts" / script), *args], cwd=root,
                          capture_output=True, text=True, encoding="utf-8", errors="replace")


def _read(path: Path) -> str | None:
    try:
        return path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _shown(names: list[str]) -> str:
    return ", ".join(names[:SHOWN_MAX]) + (f", … ({len(names)} in all)" if len(names) > SHOWN_MAX else "")


def _files(root: Path, folder: str, pattern: str = "*.md") -> list[Path]:
    base = root / folder
    return sorted(path for path in base.glob(pattern) if path.is_file()) if base.is_dir() else []


def _ideas_files(root: Path) -> list[Path]:
    return [path for path in _files(root, CONCEPT) if path.name.startswith("ideas-") and path.name != "ideas-.md"]


def _concept_pages(root: Path) -> list[Path]:
    return [path for path in _files(root, CONCEPT)
            if path.name.lower() != "readme.md" and not path.name.startswith("ideas-")]


def _proposal_files(root: Path) -> list[Path]:
    return [path for path in _files(root, PROPOSALS) if path.name.lower() != "readme.md"]


def _whiteboard_target(root: Path, ideas: Path) -> Path:
    return root / WHITEBOARD_DIR / ("whiteboard-" + ideas.name[len("ideas-"):])


def _key(rel: str) -> str:
    """A project-relative path as it is compared (a link may spell the case of a file differently on Windows)."""
    return os.path.normcase(rel)


def _loose_files(root: Path) -> list[Path]:
    """The files directly in docs/ai/concept/ that are not Markdown (pictures and the like)."""
    base = root / CONCEPT
    return sorted(path for path in base.iterdir() if path.is_file() and path.suffix.lower() != ".md") \
        if base.is_dir() else []


def _links_by_file(root: Path, skip: set[Path]) -> dict[str, set[str]]:
    """{normalized project-relative Markdown path: normalized paths of the files it links by a link that resolves to
    an existing file} for every Markdown file below docs/ except the journal and `skip`. Asked of the project's
    own entries.py in a fresh interpreter. An answer that does not come leaves the map empty: nothing moves then."""
    docs = root / "docs"
    rels = [_rel(root, path) for path in (sorted(docs.rglob("*.md")) if docs.is_dir() else [])
            if path not in skip and not _rel(root, path).startswith(_JOURNAL)]
    result = subprocess.run([sys.executable, "-c", _LINKED_FILES, str(root), str(root / ".act" / "scripts")],
                            cwd=root, input=json.dumps(rels).encode("utf-8"), capture_output=True)
    try:
        answer = json.loads(result.stdout.decode("utf-8", "replace").strip().splitlines()[-1])
    except (IndexError, ValueError):
        return {}
    return {_key(rel): {_key(found) for found in files} for rel, files in answer.items()} \
        if result.returncode == 0 and isinstance(answer, dict) else {}


def _protected(root: Path) -> list[Path]:
    """The files of a person's whiteboard: every whiteboard in docs/ai/ and every ideas file still in docs/ai/concept/.
    None of them changes by a byte in this migration."""
    return sorted(path for path in _files(root, WHITEBOARD_DIR, "whiteboard-*.md")) + _ideas_files(root)


def _keep_bytes(saved: dict[Path, bytes]) -> list[str]:
    """Puts back every file of `saved` that differs from its saved bytes; returns the file names it had to put back."""
    restored: list[str] = []
    for path, data in saved.items():
        try:
            now = path.read_bytes()
        except OSError:
            now = None
        if now != data:
            path.write_bytes(data)
            restored.append(path.name)
    return restored


def _split_proposal(text: str) -> tuple[dict[str, str], str]:
    """(header fields, rest) of a proposal file: a `---` frontmatter or the plain `key: value` lines up to the first blank
    line; the rest is what follows, without its first `# ` heading line."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff").split("\n")
    fields: dict[str, str] = {}
    start = 0
    if lines and lines[0].strip() == "---":
        end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
        if end is not None:
            for line in lines[1:end]:
                key, sep, value = line.partition(":")
                if sep:
                    fields[key.strip().lower()] = value.strip()
            start = end + 1
    else:
        while start < len(lines) and re.match(r"^[A-Za-z][\w-]*:\s", lines[start]):
            key, _sep, value = lines[start].partition(":")
            fields[key.strip().lower()] = value.strip()
            start += 1
    rest = lines[start:]
    for i, line in enumerate(rest):
        if line.strip():
            if line.startswith("# "):
                fields.setdefault("_title", line[2:].strip())
                rest = rest[:i] + rest[i + 1:]
            break
    return fields, "\n".join(rest).strip("\n")


_TARGETS = ("rules", "coding", "checklists", "config")
_JOURNAL = ("docs/ai/work/archive/", "docs/ai/work/ledger/")
_INDEX_ROW = "| `concepts/` | Open concepts: ideas worked out, not yet decided or built | current |"


def _path_pattern(old_rel: str) -> "re.Pattern[str]":
    """A project-relative path as a whole path, not the tail of a longer one (the pattern entries.py and move_doc.py use)."""
    return re.compile(r"(?<![\w./\-])" + re.escape(old_rel) + r"(?![\w\-]|\.\w)")


def _repoint(root: Path, moved: dict[str, str], pages: list[Path], whiteboards: list[Path]) -> list[str]:
    """After the ideas files moved: the old project-relative path written in a Markdown file below docs/ (not the
    journal, not a whiteboard, not an ideas file left in place: `whiteboards` lists those) becomes the new one, and a
    concept page's relative link to an ideas file follows. Returns the project-relative paths written."""
    changed: list[str] = []
    skip = set(whiteboards)
    docs = root / "docs"
    for path in sorted(docs.rglob("*.md")) if docs.is_dir() else []:
        rel = _rel(root, path)
        if path in skip or rel.startswith(_JOURNAL):
            continue
        try:
            raw = path.read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        text = raw
        for old_rel, new_rel in moved.items():
            text = _path_pattern(old_rel).sub(lambda _m, n=new_rel: n, text)
            if path in pages:
                old_link = os.path.relpath(root / old_rel, path.parent).replace(os.sep, "/")
                new_link = os.path.relpath(root / new_rel, path.parent).replace(os.sep, "/")
                text = text.replace(f"]({old_link}", f"]({new_link}").replace(f"]( {old_link}", f"]( {new_link}")
        if text != raw and not _LINKS.link_problem(root, path):
            path.write_bytes(text.encode("utf-8"))
            changed.append(rel)
    return changed


def _linked_pages(root: Path, whiteboards: list[Path], pages: list[str]) -> list[str]:
    """The whiteboards (and ideas files left in place) that link a moved concept page by its old relative name or
    name it by its old written path; they stay unchanged."""
    found: list[str] = []
    for board in whiteboards:
        text = _read(board) or ""
        for name in pages:
            how = []
            if re.search(r"\]\(\s*<?(?:\./)?" + re.escape(name) + r"[)#>\s]", text):
                how.append(f"links {name}")
            if _path_pattern(f"{CONCEPT}/{name}").search(text):
                how.append(f"names {CONCEPT}/{name}")
            if how:
                found.append(f"{_rel(root, board)} {' and '.join(how)}, which moved to {CONCEPTS_NEW}/{name} "
                             "(the file stays unchanged: fix it by hand)")
    return found


def _index_concepts(root: Path) -> bool:
    """A row for concepts/ in docs/project/README.md when it has a table and no line naming concepts/."""
    path = root / "docs" / "project" / "README.md"
    raw = _read(path)
    if raw is None or "concepts/" in raw or _LINKS.link_problem(root, path):
        return False
    lines = raw.split("\n")
    rows = [i for i, line in enumerate(lines) if line.lstrip().startswith("|")]
    if not rows:
        return False
    ending = "\r" if lines[rows[-1]].endswith("\r") else ""
    lines.insert(rows[-1] + 1, _INDEX_ROW + ending)
    path.write_bytes("\n".join(lines).encode("utf-8"))
    return True


def _proposal_item(path: Path, text: str) -> dict:
    fields, body = _split_proposal(text)
    author = fields.get("author", "").strip() or "unknown"
    if fields.get("date"):
        author = f"{author}, {fields['date']}"
    target = fields.get("target", "").strip().lower()
    return {"title": fields.get("_title") or path.stem, "body": body, "author": author,
            "target": target if target in _TARGETS else "rules"}


def _row_cells(line: str) -> list[str] | None:
    stripped = line.strip()
    if not (stripped.startswith("|") and stripped.endswith("|")):
        return None
    return [cell.strip() for cell in stripped.strip("|").split("|")]


def _readme_rows(root: Path, text: str) -> tuple[list[tuple[int, str]], list[str]]:
    """([(line index, new row)] for the old rows standing word for word, [first cells of old rows that were changed])."""
    bridge = _read(root / BRIDGE)
    new_rows: dict[str, str] = {}
    for line in (bridge or "").splitlines():
        cells = _row_cells(line)
        if cells:
            new_rows[cells[0]] = line
    lines = text.split("\n")
    replace: list[tuple[int, str]] = []
    changed: list[str] = []
    today = date.today().isoformat()
    for first, second, fourth, new_first in OLD_ROWS:
        hit = None
        near = None
        for index, line in enumerate(lines):
            cells = _row_cells(line.rstrip("\r"))
            if not cells or len(cells) != 4:
                continue
            if cells[0] == first:
                if cells[1] == second and cells[3] == fourth:
                    hit = index
                else:
                    near = first
                break
        if hit is not None and new_first in new_rows:
            replace.append((hit, new_rows[new_first].replace("<today>", today)))
        elif near is not None:
            changed.append(near)
    return replace, changed


# ---------------------------------------------------------------------------
# plan / apply
# ---------------------------------------------------------------------------

def plan(root: Path) -> str:
    parts: list[str] = []
    ideas = _ideas_files(root)
    if ideas:
        parts.append("move " + _shown([f"{_rel(root, path)} -> {_rel(root, _whiteboard_target(root, path))}"
                                       for path in ideas]))
    pages = _concept_pages(root)
    if pages:
        parts.append(f"move {len(pages)} concept page(s) to {CONCEPTS_NEW}/: " + _shown([p.name for p in pages]))
    proposals = _proposal_files(root)
    if proposals:
        parts.append(f"turn {len(proposals)} proposal(s) into inbox questions: " + _shown([p.name for p in proposals]))
    readmes = [name for name in (CONCEPT, PROPOSALS) if (root / name / "README.md").is_file()]
    if readmes:
        parts.append("archive the README.md of " + " and ".join(f"{name}/" for name in readmes))
    folders = [name for name in (CONCEPT, PROPOSALS) if (root / name).is_dir()]
    if folders:
        parts.append("remove " + " and ".join(f"{name}/" for name in folders) + " once empty")
    text = _read(root / DOCS_README)
    if text is not None and _readme_rows(root, text)[0]:
        parts.append(f"replace the template's two old rows in {DOCS_README}")
    if (root / "docs" / "ai").is_dir() and not (root / WHITEBOARD_DIR / "README.md").exists() and parts:
        parts.insert(0, f"create {WHITEBOARD_DIR}/README.md")
    return "; ".join(parts) if parts else "nothing to do (no ideas files, no proposals folder)"


def _skeleton_readme(root: Path) -> Path | None:
    for candidate in (root / "docs" / "ai" / "local" / "skeleton" / "README.md",
                      root / ".act" / "skeleton" / "README.md"):
        if candidate.is_file():
            return candidate
    return None


def apply(root: Path) -> tuple[str, list[str]]:
    done: list[str] = []
    left: list[str] = []
    touched: list[str] = []
    check = _LINKS.LinkCheck(root)

    def blocked(*paths: Path) -> str:
        for path in paths:
            reason = check.problem(path)
            if reason:
                return reason
        return ""

    ideas = _ideas_files(root)
    pages = _concept_pages(root)
    proposals = _proposal_files(root)
    if not (ideas or pages or proposals or (root / CONCEPT / "README.md").is_file()
            or (root / PROPOSALS / "README.md").is_file() or (root / CONCEPT).is_dir()
            or (root / PROPOSALS).is_dir()):
        return "nothing to do (no ideas files, no proposals folder)", []

    # 1. the rules for the whiteboards
    readme = root / WHITEBOARD_DIR / "README.md"
    source = _skeleton_readme(root)
    created_readme = False
    if not readme.exists() and source is not None and not blocked(readme):
        created_readme = True
        _LINKS.write_new(readme, source.read_bytes().replace(b"\r\n", b"\n"))
        touched.append(_rel(root, readme))
        done.append(f"created {_rel(root, readme)}")

    # 2. the ideas files, and the files they link beside them
    moved_ideas = 0
    moved_map: dict[str, str] = {}
    loose = _loose_files(root)
    links: dict[str, set[str]] = {}
    if ideas and loose:  # asked before anything moves
        links = _links_by_file(root, {readme} if created_readme else set())
    for path in ideas:
        target = _whiteboard_target(root, path)
        reason = blocked(path, target)
        if reason:
            left.append(f"{_rel(root, path)} ({reason})")
        elif target.exists():
            left.append(f"{_rel(root, path)} (the whiteboard {_rel(root, target)} exists already)")
        else:
            os.replace(path, target)
            touched += [_rel(root, path), _rel(root, target)]
            moved_map[_rel(root, path)] = _rel(root, target)
            moved_ideas += 1
    if moved_ideas:
        done.append(f"moved {moved_ideas} ideas file(s) to {WHITEBOARD_DIR}/whiteboard-<identity>.md")
    movers = {_key(rel) for rel in moved_map}
    for path in loose:
        linkers = {rel for rel, found in links.items() if _key(_rel(root, path)) in found}
        if not linkers & movers:
            continue  # no ideas file that moved links it: it stays with whatever is left in docs/ai/concept/
        target = root / WHITEBOARD_DIR / path.name
        if blocked(path, target):
            left.append(f"{_rel(root, path)} (a link on its way)")
        elif linkers - movers:
            left.append(f"{_rel(root, path)} (linked by a moved whiteboard, but also by "
                        f"{_shown(sorted(linkers - movers))}, so it stays - check the links)")
        elif target.exists():
            left.append(f"{_rel(root, path)} (linked by a moved whiteboard, but its name is taken in "
                        f"{WHITEBOARD_DIR}/ - check the link)")
        else:
            os.replace(path, target)
            touched += [_rel(root, path), _rel(root, target)]
            done.append(f"moved {path.name} beside the whiteboards")

    # 3. concept pages (the whiteboards and the ideas files left in place keep every byte)
    moved_pages = 0
    protected = _protected(root)
    saved = {path: path.read_bytes() for path in protected}
    protected_rels = {_rel(root, path) for path in protected}
    for path in pages:
        target = root / CONCEPTS_NEW / path.name
        if blocked(path, target) or target.exists():
            left.append(f"{_rel(root, path)} ({_rel(root, target)} exists already or a link is in the way)")
            continue
        result = _run(root, "move_doc.py", _rel(root, path), _rel(root, target), "--apply", "--root", str(root))
        _keep_bytes(saved)
        if result.returncode != 0:
            left.append(f"{_rel(root, path)} (move_doc.py: {(result.stderr or result.stdout).strip()[:160]})")
            continue
        moved_pages += 1
        touched += [_rel(root, path), _rel(root, target)]
        for line in result.stdout.splitlines():
            if line.startswith("  references or index: "):
                changed_rel = line[len("  references or index: "):].strip()
                if changed_rel not in protected_rels:
                    touched.append(changed_rel)
            elif line.startswith("  by hand: "):
                left.append(line[len("  by hand: "):].strip())
    if moved_pages:
        done.append(f"moved {moved_pages} concept page(s) to {CONCEPTS_NEW}/")
        if _index_concepts(root):
            touched.append("docs/project/README.md")
            done.append("added a row for concepts/ to docs/project/README.md")
        left += _linked_pages(root, protected, [page.name for page in pages if not (root / CONCEPT / page.name).exists()])
    if moved_map:
        # a concept page wherever it is now: moved, or left in docs/ai/concept/ because its name is taken
        now_pages = [root / CONCEPT / page.name if (root / CONCEPT / page.name).is_file()
                     else root / CONCEPTS_NEW / page.name for page in pages]
        touched += _repoint(root, moved_map, [path for path in now_pages if path.is_file()], protected)

    # 4. proposals
    items: list[dict] = []
    sources: list[Path] = []
    for path in proposals:
        text = _read(path)
        archived = root / PROPOSALS_ARCHIVE / path.name
        if text is None:
            left.append(f"{_rel(root, path)} (not UTF-8)")
        elif archived.exists() or blocked(path, archived):
            left.append(f"{_rel(root, path)} ({_rel(root, archived)} exists already or a link is in the way)")
        else:
            items.append(_proposal_item(path, text))
            sources.append(path)
    if items:
        inbox = root / "docs" / "ai" / "inbox"
        before = {path.name for path in inbox.iterdir()} if inbox.is_dir() else set()
        result = subprocess.run([sys.executable, "-c", _FILE_QUESTIONS, str(root), str(root / ".act" / "scripts")],
                                cwd=root, input=json.dumps(items).encode("utf-8"), capture_output=True)
        made: list[str] = []
        for line in result.stdout.decode("utf-8", "replace").splitlines():
            try:
                value = json.loads(line)
            except ValueError:
                continue
            if isinstance(value, str):
                made.append(value)
        made = made[:len(sources)]
        # every file the run wrote is touched, also one it wrote and did not report
        if inbox.is_dir():
            touched += [_rel(root, path) for path in sorted(inbox.iterdir()) if path.name not in before]
        if made:
            (root / PROPOSALS_ARCHIVE).mkdir(parents=True, exist_ok=True)
        for path, question in zip(sources, made):  # the proposals whose question is filed move on, the others stay
            target = root / PROPOSALS_ARCHIVE / path.name
            os.replace(path, target)
            touched += [question, _rel(root, path), _rel(root, target)]
        if made:
            done.append(f"turned {len(made)} proposal(s) into inbox questions (the files are in {PROPOSALS_ARCHIVE}/)")
        if len(made) != len(sources):
            why = result.stderr.decode("utf-8", "replace").strip().splitlines()
            reason = why[-1][:160] if why else "no answer"
            left.append(f"filing questions stopped after {len(made)} of {len(sources)}: filed "
                        f"{_shown([path.name for path in sources[:len(made)]]) or 'none'}; not filed "
                        f"{_shown([path.name for path in sources[len(made):]])} ({reason}) - they stay in "
                        f"{PROPOSALS}/, run the update again after fixing the cause")

    # 5. the READMEs, then the folders
    for folder in (CONCEPT, PROPOSALS):
        file = root / folder / "README.md"
        if not file.is_file():
            continue
        result = _run(root, "entries.py", "archive", _rel(root, file))
        if result.returncode == 0:
            touched.append(_rel(root, file))
            for line in result.stdout.splitlines():
                touched += re.findall(r"docs/[^\s()]+", line)
            done.append(f"archived {folder}/README.md")
        else:
            left.append(f"{folder}/README.md (entries.py archive: {(result.stderr or result.stdout).strip()[:160]})")
    for folder in (CONCEPT, PROPOSALS):
        path = root / folder
        if path.is_dir() and not path.is_symlink():
            try:
                path.rmdir()
                done.append(f"removed {folder}/")
            except OSError:
                names = sorted(item.name for item in path.iterdir())
                left.append(f"{folder}/ is not empty ({_shown(names)})")

    # 6. docs/README.md
    readme_path = root / DOCS_README
    raw = _read(readme_path)
    if raw is not None and not blocked(readme_path):
        replace, changed = _readme_rows(root, raw)
        if replace:
            lines = raw.split("\n")
            for index, row in replace:
                ending = "\r" if lines[index].endswith("\r") else ""
                lines[index] = row + ending
            readme_path.write_bytes("\n".join(lines).encode("utf-8"))
            touched.append(DOCS_README)
            done.append(f"replaced {len(replace)} row(s) in {DOCS_README}")
        for first in changed:
            left.append(f"{DOCS_README}: the row for {first} was changed, so it stays - write the rows of "
                        "docs/ai/whiteboard-<identity>.md and docs/ai/inbox/ yourself")

    unique = sorted(dict.fromkeys(touched))
    description = "; ".join(done) if done else "nothing changed"
    if left:
        description += "; left in place: " + "; ".join(left)
    return description, unique
