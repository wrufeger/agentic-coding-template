#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Check a project's translation files for completeness and consistency — the mechanical
#          half of skill `act-check-translations`. Code-only: reads files, never runs the app,
#          never calls a browser or a translation service, writes nothing.
#
# Detection: translation files are JSON or simple YAML (`key: value`, nested by indentation) inside
#          a directory named locales, locale, i18n, lang, languages, messages, translations or l10n
#          (anywhere below the root, vendored and build folders skipped). Two layouts are read:
#          one file per locale (`locales/en.json`) and one folder per locale with namespace files
#          (`locales/en/common.json`, keys become `common.<key>`).
#
# Findings (type, severity):
#   missing               warning  key in the base locale, absent in another locale
#   extra                 warning  key in a locale, absent in the base locale
#   empty                 warning  key present with an empty value
#   placeholder-mismatch  error    `{name}`, `{{name}}`, `%{name}`, `%s`, `:name` differ from the base
#   used-undefined        error    key used in source code (t('..'), $t(".."), __('..') ...), not in base
#   unused                info     key in the base locale that no source call mentions (best effort:
#                                  dynamic keys are guessed from their literal prefix)
#   parse-error           error    a translation file could not be read
#
# Usage:
#   python .act/scripts/i18n_check.py [--root DIR] [--base LOCALE] [--json] [--no-code]
#
# Exit code: 0 no finding above info, 1 at least one warning or error, 2 usage problem.

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterator, Optional

LOCALE_DIR_NAMES = {"locales", "locale", "i18n", "lang", "languages", "messages", "translations", "l10n"}
SKIP_DIRS = {
    ".git", "node_modules", "vendor", "dist", "build", ".venv", "venv", "__pycache__", ".act", ".act-local",
    ".nuxt", ".next", ".output", "coverage", "target", ".claude", ".agents", ".idea", ".vscode",
}
SOURCE_SUFFIXES = {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".vue", ".svelte", ".py", ".php", ".html",
                   ".twig", ".erb", ".astro", ".jinja", ".j2"}
LOCALE_NAME = re.compile(r"^[a-z]{2,3}(?:[-_][A-Za-z0-9]{2,4})?$")
MAX_FILE_BYTES = 2_000_000
MAX_JSON_DEPTH = 100

SEVERITY = {
    "parse-error": "error", "placeholder-mismatch": "error", "used-undefined": "error",
    "missing": "warning", "extra": "warning", "empty": "warning", "unused": "info",
}

# translation call forms: t('k'), $t("k"), i18n.t('k'), this.$t('k'), __('k'), trans('k'), gettext('k'), $tc('k')
CALL = re.compile(r"""(?<![\w$.])(?:\$t|\$tc|t|tc|i18n\.t|\$?trans|trans_choice|__|gettext|_)\(\s*(['"])((?:(?!\1).)+)\1""")
CALL_METHOD = re.compile(r"""(?:\.\$?t|\.\$tc|\.translate)\(\s*(['"])((?:(?!\1).)+)\1""")
DYNAMIC_TEMPLATE = re.compile(r"""(?<![\w$.])(?:\$t|\$tc|t|tc|i18n\.t|\$?trans|__)\(\s*`([^`$]*)\$\{""")
DYNAMIC_CONCAT = re.compile(r"""(?<![\w$.])(?:\$t|\$tc|t|tc|i18n\.t|\$?trans|__)\(\s*(['"])([^'"]*)\1\s*[+.]""")


@dataclass
class Finding:
    type: str
    severity: str
    detail: str
    locale: str = ""
    key: str = ""
    file: str = ""


@dataclass
class LocaleData:
    name: str
    files: list[str] = field(default_factory=list)
    values: dict[str, str] = field(default_factory=dict)


@dataclass
class Group:
    directory: str
    locales: dict[str, LocaleData] = field(default_factory=dict)


def flatten_json(node: object, prefix: str, out: dict[str, str], depth: int = 0) -> None:
    """Flatten nested JSON into dotted keys; scalars become strings, null becomes empty."""
    if depth > MAX_JSON_DEPTH:
        raise ValueError(f"nested deeper than {MAX_JSON_DEPTH} levels")
    if isinstance(node, dict):
        if not node and prefix:
            out[prefix] = ""
        for key, value in node.items():
            flatten_json(value, f"{prefix}.{key}" if prefix else str(key), out, depth + 1)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            flatten_json(value, f"{prefix}.{index}" if prefix else str(index), out, depth + 1)
    elif node is None:
        out[prefix] = ""
    else:
        out[prefix] = str(node)


def unquote(raw: str) -> str:
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "'\"":
        return raw[1:-1]
    return raw


def parse_yaml(text: str) -> dict[str, str]:
    """Simple YAML only: nested `key: value` by indentation, comments, block scalars, list items.
    Anchors, flow collections, multi-document files and complex keys are not understood."""
    out: dict[str, str] = {}
    stack: list[tuple[int, str]] = []  # (indent, key)
    lines = text.splitlines()
    index = 0
    last_key = ""
    while index < len(lines):
        line = lines[index]
        index += 1
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped in ("---", "..."):
            continue
        indent = len(line) - len(line.lstrip(" "))
        if stripped.startswith("- "):
            if last_key:
                out[last_key] = out.get(last_key) or stripped[2:].strip() or "-"
            continue
        match = re.match(r"""^(?P<key>"[^"]*"|'[^']*'|[^:#\s][^:]*?)\s*:(?:\s+(?P<value>.*))?$""", stripped)
        if not match:
            raise ValueError(f"line {index}: not a `key: value` line: {stripped[:60]!r}")
        key = unquote(match.group("key"))
        value = (match.group("value") or "").strip()
        while stack and stack[-1][0] >= indent:
            stack.pop()
        full = ".".join([k for _, k in stack] + [key])
        if value and value[0] in "|>":
            block: list[str] = []
            while index < len(lines):
                nxt = lines[index]
                if nxt.strip() and len(nxt) - len(nxt.lstrip(" ")) <= indent:
                    break
                block.append(nxt.strip())
                index += 1
            out[full] = " ".join(b for b in block if b)
            last_key = full
        elif value == "" or value.startswith("#"):
            stack.append((indent, key))
            out[full] = ""
            last_key = full
        else:
            if value[0] not in "'\"":
                value = re.sub(r"\s+#.*$", "", value)
            out[full] = unquote(value)
            last_key = full
    # a key that only has children is a container, not an empty value
    parents = {k.rsplit(".", 1)[0] for k in out if "." in k}
    return {k: v for k, v in out.items() if not (v == "" and k in parents)}


def read_bounded(path: Path, errors: str = "strict", encoding: str = "utf-8-sig") -> str:
    """Text of a regular file, at most MAX_FILE_BYTES; a symlink, FIFO or device is refused without opening it."""
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError("not a regular file (symlink, FIFO or device)")
    with path.open("rb") as handle:
        raw = handle.read(MAX_FILE_BYTES + 1)
    if len(raw) > MAX_FILE_BYTES:
        raise ValueError(f"file larger than {MAX_FILE_BYTES} bytes")
    return raw.decode(encoding, errors)


def read_translation_file(path: Path) -> dict[str, str]:
    text = read_bounded(path)
    if path.suffix.lower() == ".json":
        out: dict[str, str] = {}
        flatten_json(json.loads(text), "", out)
        return out
    return parse_yaml(text)


def walk(root: Path) -> Iterator[tuple[Path, list[str]]]:
    for current, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        yield Path(current), sorted(files)


def locale_of(stem: str) -> Optional[str]:
    """The locale a file stem names: `en`, `de-DE`, `messages.en` -> `en`; None if it is no locale."""
    if LOCALE_NAME.match(stem):
        return stem
    tail = stem.rsplit(".", 1)[-1]
    return tail if "." in stem and LOCALE_NAME.match(tail) else None


def detect_groups(root: Path, findings: list[Finding]) -> list[Group]:
    groups: dict[str, Group] = {}

    def add(directory: Path, locale: str, path: Path, prefix: str) -> None:
        group = groups.setdefault(str(directory.relative_to(root)).replace("\\", "/"),
                                  Group(str(directory.relative_to(root)).replace("\\", "/")))
        data = group.locales.setdefault(locale, LocaleData(locale))
        rel = str(path.relative_to(root)).replace("\\", "/")
        data.files.append(rel)
        try:
            values = read_translation_file(path)
        except (OSError, ValueError, RecursionError) as exc:  # JSON and Unicode decode errors are ValueErrors
            findings.append(Finding("parse-error", "error", f"{type(exc).__name__}: {exc}", locale, "", rel))
            return
        # a YAML file often wraps everything in its own locale key (`en:` at the top)
        if path.suffix.lower() in (".yml", ".yaml"):
            top = {k.split(".", 1)[0] for k in values}
            if top == {locale}:
                values = {k.split(".", 1)[1]: v for k, v in values.items() if "." in k}
        for key, value in values.items():
            data.values[f"{prefix}{key}"] = value

    for current, files in walk(root):
        if current.name.lower() not in LOCALE_DIR_NAMES:
            continue
        for name in files:
            path = current / name
            if path.suffix.lower() not in (".json", ".yml", ".yaml"):
                continue
            locale = locale_of(path.stem)
            if locale:
                add(current, locale, path, "")
        for sub in sorted(p for p in current.iterdir() if p.is_dir() and p.name not in SKIP_DIRS):
            if not LOCALE_NAME.match(sub.name):
                continue
            for inner, inner_files in walk(sub):
                for name in inner_files:
                    path = inner / name
                    if path.suffix.lower() in (".json", ".yml", ".yaml"):
                        relative = path.relative_to(sub).with_suffix("")
                        add(current, sub.name, path, ".".join(relative.parts) + ".")
    return [g for g in groups.values() if g.locales]


PLACEHOLDERS = [
    re.compile(r"\{\{\s*(\w+)\s*\}\}"), re.compile(r"%\{(\w+)\}"), re.compile(r"\{(\w+)\}"),
    re.compile(r"(%(?:\d+\$)?[sdif])"), re.compile(r"(?<![\w:]):([A-Za-z_]\w*)"),
]


def placeholders(value: str) -> list[str]:
    found: list[str] = []
    for pattern in PLACEHOLDERS:
        for match in pattern.finditer(value):
            found.append(match.group(0).replace(" ", ""))
        value = pattern.sub(" ", value)  # do not count `{{name}}` again as `{name}`
    return sorted(found)


def pick_base(group: Group, wanted: Optional[str]) -> str:
    if wanted and wanted in group.locales:
        return wanted
    if "en" in group.locales:
        return "en"
    return max(group.locales.values(), key=lambda d: len(d.values)).name


def compare(group: Group, base: str, findings: list[Finding]) -> None:
    base_values = group.locales[base].values
    for name, data in sorted(group.locales.items()):
        file = data.files[0] if data.files else group.directory
        for key, value in sorted(data.values.items()):
            if value.strip() == "":
                findings.append(Finding("empty", "warning", "empty value", name, key, file))
        if name == base:
            continue
        for key in sorted(set(base_values) - set(data.values)):
            findings.append(Finding("missing", "warning", f"in {base}, absent here", name, key, file))
        for key in sorted(set(data.values) - set(base_values)):
            findings.append(Finding("extra", "warning", f"absent in base locale {base}", name, key, file))
        for key in sorted(set(base_values) & set(data.values)):
            have, want = placeholders(data.values[key]), placeholders(base_values[key])
            if base_values[key].strip() and data.values[key].strip() and have != want:
                findings.append(Finding("placeholder-mismatch", "error",
                                        f"{base} has {want or 'none'}, here {have or 'none'}", name, key, file))


def scan_code(root: Path) -> tuple[dict[str, str], list[str], int]:
    """Keys used in source (key -> first `path:line`), dynamic key prefixes, number of source files read."""
    used: dict[str, str] = {}
    prefixes: list[str] = []
    count = 0
    for current, files in walk(root):
        if current.name.lower() in LOCALE_DIR_NAMES:
            continue
        for name in files:
            path = current / name
            if path.suffix.lower() not in SOURCE_SUFFIXES:
                continue
            try:
                lines = read_bounded(path, "replace", "utf-8").splitlines()
            except (OSError, ValueError):
                continue
            count += 1
            rel = str(path.relative_to(root)).replace("\\", "/")
            for number, line in enumerate(lines, 1):
                for pattern in (CALL, CALL_METHOD):
                    for match in pattern.finditer(line):
                        used.setdefault(match.group(2), f"{rel}:{number}")
                prefixes += [m.group(1) for m in DYNAMIC_TEMPLATE.finditer(line)]
                prefixes += [m.group(2) for m in DYNAMIC_CONCAT.finditer(line)]
    return used, [p for p in prefixes if p], count


def normalize_key(key: str, known: set[str]) -> str:
    """i18next `namespace:key` -> `namespace.key`; used keys are matched against the base as written first."""
    if key in known or " " in key or ":" not in key:
        return key
    return key.replace(":", ".", 1)


def check_code(scan: tuple[dict[str, str], list[str], int], group: Group, base: str,
               findings: list[Finding]) -> int:
    used, prefixes, count = scan
    if not used:
        return count
    base_values = group.locales[base].values
    known = set(base_values)
    text_keys = any(" " in k for k in known)
    resolved: set[str] = set()
    for raw, where in sorted(used.items()):
        key = normalize_key(raw, known)
        resolved.add(key)
        if key in known:
            continue
        if " " in key and not text_keys:
            continue  # looks like plain text in a function named t/_/__, not a key
        if not re.fullmatch(r"[\w.\-: ]+", key) and not text_keys:
            continue
        # a call with a plural/suffix form: `key` absent but `key.one`/`key.other` present
        if any(k.startswith(key + ".") for k in known):
            continue
        findings.append(Finding("used-undefined", "error", f"used at {where}, missing in base locale {base}",
                                base, key, where.rsplit(":", 1)[0]))
    for key in sorted(known):
        if key in resolved or any(key.startswith(p) for p in prefixes):
            continue
        if any(key.startswith(r + ".") or r.startswith(key + ".") for r in resolved):
            continue
        findings.append(Finding("unused", "info", "no source call mentions it", base, key,
                                group.locales[base].files[0] if group.locales[base].files else ""))
    return count


def render(report: dict) -> str:
    lines: list[str] = []
    if not report["groups"]:
        return "No translation files found (looked for JSON/YAML in locales, i18n, lang, messages, translations, l10n)."
    for group in report["groups"]:
        lines.append(f"{group['directory']}  base: {group['base']}  locales: "
                     + ", ".join(f"{n} ({c} keys)" for n, c in group["locales"].items()))
    lines.append(f"source files read: {report['source_files']}")
    findings = report["findings"]
    if not findings:
        lines.append("\nNo findings.")
        return "\n".join(lines)
    lines.append("")
    for kind in SEVERITY:
        items = [f for f in findings if f["type"] == kind]
        if not items:
            continue
        lines.append(f"{kind} ({SEVERITY[kind]}): {len(items)}")
        for item in items[:50]:
            place = f"[{item['locale']}] " if item["locale"] else ""
            lines.append(f"  {place}{item['key'] or item['file']}  - {item['detail']}")
        if len(items) > 50:
            lines.append(f"  ... {len(items) - 50} more (use --json)")
    return "\n".join(lines)


def run(root: Path, base: Optional[str], use_code: bool) -> dict:
    findings: list[Finding] = []
    groups = detect_groups(root, findings)
    source_files = 0
    summary: list[dict] = []
    scan: tuple[dict[str, str], list[str], int] = scan_code(root) if use_code and groups else ({}, [], 0)
    for group in groups:
        chosen = pick_base(group, base)
        compare(group, chosen, findings)
        if use_code:
            source_files = max(source_files, check_code(scan, group, chosen, findings))
        summary.append({"directory": group.directory, "base": chosen,
                        "locales": {n: len(d.values) for n, d in sorted(group.locales.items())}})
    return {"root": str(root), "groups": summary, "source_files": source_files,
            "findings": [asdict(f) for f in findings]}


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Check translation files for missing, extra, empty and "
                                     "mismatching keys and for keys used in code but not defined.")
    parser.add_argument("--root", default=".", help="project root (default: current directory)")
    parser.add_argument("--base", default=None, help="base locale (default: en, else the largest)")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    parser.add_argument("--no-code", action="store_true", help="skip the used/unused key check against source code")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"Not a directory: {root}", file=sys.stderr)
        return 2
    report = run(root, args.base, not args.no_code)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(render(report))
    return 1 if any(f["severity"] in ("error", "warning") for f in report["findings"]) else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
