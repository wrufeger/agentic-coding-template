#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: One-time, per-machine setup of the clickable entry ids (editor support). Copies the language
#          server and its helper to a per-user folder, packs the VS Code extension as a .vsix file and
#          writes an import template for IntelliJ (LSP4IJ plugin). Installs nothing into an editor and
#          starts no editor: it prints the next steps and the way back.
#          Stdlib only, Python 3.9 or newer. No network, no other program is started.
#
# Usage:
#   python .act/scripts/id_links_install.py              # write under ~/.act/id-links/
#   python .act/scripts/id_links_install.py --home DIR   # write under DIR/.act/id-links/ instead of ~
#   python .act/scripts/id_links_install.py --help       # print this description and exit
#
# Writes (only below <home>/.act/id-links/, created if missing, overwritten on a second run):
#   id_links_lsp.py, actlib.py            copies of the server and its helper; the editor starts these
#                                         copies, never a file inside a repository
#   lsp4ij/template.json                  import template for IntelliJ (LSP4IJ); its program arguments
#                                         name the base interpreter (never a virtual environment) with
#                                         -I -S and the copy above by absolute path
#   act-id-links-<version>.vsix           the VS Code extension (a zip), version from its package.json
#
# Output format: the files written, then the next steps per editor and the way back, on stdout. Errors
#        go to stderr naming the path. Exit code 0 on success, 1 on a failure (a missing source file
#        or a path that cannot be written), 2 on a usage error.

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path
from typing import Optional
from xml.sax.saxutils import escape, quoteattr

SCRIPTS_DIR = Path(__file__).resolve().parent
ACT_DIR = SCRIPTS_DIR.parent
VSCODE_SRC = ACT_DIR / "ide" / "vscode"
LICENSE_SRC = VSCODE_SRC / "LICENSE.txt"  # the template's own license; a project's root LICENSE may be its own
TARGET_NAME = "id-links"
SERVER_NAME = "id_links_lsp.py"
HELPER_NAME = "actlib.py"
START_FLAGS = "-I -S"
# Fixed timestamp so that a second run produces a byte-identical .vsix.
ZIP_TIME = (2020, 1, 1, 0, 0, 0)

CONTENT_TYPES = (
    '<?xml version="1.0" encoding="utf-8"?>\n'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">\n'
    '  <Default Extension=".json" ContentType="application/json"/>\n'
    '  <Default Extension=".vsixmanifest" ContentType="text/xml"/>\n'
    '  <Default Extension=".js" ContentType="application/javascript"/>\n'
    '  <Default Extension=".md" ContentType="text/markdown"/>\n'
    '  <Default Extension=".txt" ContentType="text/plain"/>\n'
    '</Types>\n'
)


class InstallError(Exception):
    """A failure with the path it concerns in the message."""


def read_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as error:
        raise InstallError(f"cannot read {path}: {error.strerror or type(error).__name__}") from error


def write_bytes(path: Path, data: bytes) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    except OSError as error:
        raise InstallError(f"cannot write {path}: {error.strerror or type(error).__name__}") from error


def quote_arg(value: str) -> str:
    """One command-line word in double quotes for a POSIX shell, so a path with spaces stays one word."""
    escaped = value
    for char in ("\\", '"', "$", "`"):
        escaped = escaped.replace(char, "\\" + char)
    return f'"{escaped}"'


def choose_interpreter() -> tuple[Path, bool]:
    """The interpreter the editor will start, and whether a virtual environment was replaced by its base.
    A venv inside a repository (with its .pth files) must not be what an editor runs, and it may be deleted."""
    if sys.prefix != getattr(sys, "base_prefix", sys.prefix):
        base = getattr(sys, "_base_executable", None)
        if base and Path(base).absolute() != Path(sys.executable).absolute():
            return Path(base).absolute(), True
    return Path(sys.executable).absolute(), False


def command_line(interpreter: Path, server: Path, windows: bool) -> str:
    """`"<interpreter>" -I -S "<server>"`; Windows paths keep their backslashes (cmd and CreateProcess do not
    treat a backslash as an escape), POSIX paths are escaped for the shell. `-I -S`: isolated mode (ignores
    PYTHONPATH, PYTHONHOME, user site) and no site module (no .pth files); the server puts its own folder
    on sys.path itself."""
    if windows:
        return f'"{interpreter}" {START_FLAGS} "{server}"'
    return f"{quote_arg(str(interpreter))} {START_FLAGS} {quote_arg(str(server))}"


def build_template(interpreter: Path, server: Path) -> dict[str, object]:
    return {
        "id": "act-id-links",
        "name": "ACT ID Links",
        "programArgs": {
            "default": command_line(interpreter, server, windows=sys.platform == "win32"),
            "windows": command_line(interpreter, server, windows=True),
        },
        "fileTypeMappings": [
            {"fileType": {"name": "Markdown", "patterns": ["*.md"]}, "languageId": "markdown"},
        ],
    }


def vsix_manifest(package: dict[str, object], has_license: bool) -> str:
    """extension.vsixmanifest, the form `vsce` writes: identity, engine, installation target, assets."""
    name, publisher, version = (str(package[key]) for key in ("name", "publisher", "version"))
    engine = str((package.get("engines") or {}).get("vscode", "*"))  # type: ignore[attr-defined]
    display = str(package.get("displayName", name))
    description = str(package.get("description", ""))
    categories = ",".join(str(item) for item in package.get("categories", []))  # type: ignore[attr-defined]
    assets = [
        ("Microsoft.VisualStudio.Code.Manifest", "extension/package.json"),
        ("Microsoft.VisualStudio.Services.Content.Details", "extension/README.md"),
    ]
    if has_license:
        assets.append(("Microsoft.VisualStudio.Services.Content.License", "extension/LICENSE.txt"))
    asset_lines = "\n".join(
        f"    <Asset Type={quoteattr(kind)} d:Source=\"File\" Path={quoteattr(path)} Addressable=\"true\" />"
        for kind, path in assets)
    license_line = "    <License>extension/LICENSE.txt</License>\n" if has_license else ""
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<PackageManifest Version="2.0.0" xmlns="http://schemas.microsoft.com/developer/vsx-schema/2011" '
        'xmlns:d="http://schemas.microsoft.com/developer/vsx-schema-design/2011">\n'
        '  <Metadata>\n'
        f'    <Identity Language="en-US" Id={quoteattr(name)} Version={quoteattr(version)} '
        f'Publisher={quoteattr(publisher)} />\n'
        f'    <DisplayName>{escape(display)}</DisplayName>\n'
        f'    <Description xml:space="preserve">{escape(description)}</Description>\n'
        f'    <Categories>{escape(categories)}</Categories>\n'
        '    <GalleryFlags>Public</GalleryFlags>\n'
        '    <Properties>\n'
        f'      <Property Id="Microsoft.VisualStudio.Code.Engine" Value={quoteattr(engine)} />\n'
        '    </Properties>\n'
        f'{license_line}'
        '  </Metadata>\n'
        '  <Installation>\n'
        '    <InstallationTarget Id="Microsoft.VisualStudio.Code" />\n'
        '  </Installation>\n'
        '  <Dependencies />\n'
        '  <Assets>\n'
        f'{asset_lines}\n'
        '  </Assets>\n'
        '</PackageManifest>\n'
    )


def build_vsix(target: Path) -> tuple[Path, bool]:
    """Write the .vsix into `target`; returns (path, whether a LICENSE.txt was packed)."""
    package_bytes = read_bytes(VSCODE_SRC / "package.json")
    try:
        package = json.loads(package_bytes.decode("utf-8"))
        version = str(package["version"])
        for key in ("name", "publisher"):
            package[key]
    except (ValueError, KeyError) as error:
        raise InstallError(f"{VSCODE_SRC / 'package.json'} is not usable: {type(error).__name__} {error}") from error
    license_bytes: Optional[bytes] = read_bytes(LICENSE_SRC) if LICENSE_SRC.is_file() else None
    entries: list[tuple[str, bytes]] = [
        ("[Content_Types].xml", CONTENT_TYPES.encode("utf-8")),
        ("extension.vsixmanifest", vsix_manifest(package, license_bytes is not None).encode("utf-8")),
        ("extension/package.json", package_bytes),
        ("extension/extension.js", read_bytes(VSCODE_SRC / "extension.js.txt")),
        ("extension/README.md", read_bytes(VSCODE_SRC / "README.md")),
    ]
    if license_bytes is not None:
        entries.append(("extension/LICENSE.txt", license_bytes))
    vsix = target / f"act-id-links-{version}.vsix"
    try:
        vsix.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(vsix, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, data in entries:
                info = zipfile.ZipInfo(name, ZIP_TIME)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                archive.writestr(info, data)
    except OSError as error:
        raise InstallError(f"cannot write {vsix}: {error.strerror or type(error).__name__}") from error
    return vsix, license_bytes is not None


def install(home: Path, interpreter: Path) -> tuple[Path, Path, Path, bool]:
    """Write everything; returns (target folder, vsix, template folder, license packed)."""
    target = home / ".act" / TARGET_NAME
    write_bytes(target / SERVER_NAME, read_bytes(SCRIPTS_DIR / SERVER_NAME))
    write_bytes(target / HELPER_NAME, read_bytes(SCRIPTS_DIR / HELPER_NAME))
    template = build_template(interpreter, (target / SERVER_NAME).absolute())
    write_bytes(target / "lsp4ij" / "template.json", (json.dumps(template, indent=2) + "\n").encode("utf-8"))
    vsix, licensed = build_vsix(target)
    return target, vsix, target / "lsp4ij", licensed


def main() -> int:
    # Output can carry an em dash; on Windows, stdout/stderr otherwise default to the console's
    # legacy code page instead of UTF-8. Same fix as the other scripts in this folder.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(
        description="Set up clickable entry ids for the editors: copies the language server to "
                    "<home>/.act/id-links/, packs the VS Code extension as a .vsix there and writes an import "
                    "template for IntelliJ (LSP4IJ). Installs nothing into an editor; prints the next steps "
                    "and the way back. Safe to run again (overwrites the same files).")
    parser.add_argument("--home", type=Path, default=None,
                        help="folder that takes the place of your home folder (default: your home folder)")
    args = parser.parse_args()
    home = (args.home if args.home is not None else Path.home()).absolute()
    interpreter, from_venv = choose_interpreter()
    try:
        target, vsix, template, licensed = install(home, interpreter)
    except InstallError as error:
        print(f"id_links_install: {error}", file=sys.stderr)
        return 1
    print(f"Written under {target}:")
    for path in (target / SERVER_NAME, target / HELPER_NAME, template / "template.json", vsix):
        print(f"  {path}")
    if not licensed:
        print("  (no .act/ide/vscode/LICENSE.txt: the .vsix carries no license file)")
    if from_venv:
        print(f"Interpreter: {interpreter} (the base interpreter; this run uses a virtual environment, "
              f"which an editor must not start)")
    else:
        print(f"Interpreter: {interpreter}")
    print(f"""
Next steps (nothing is installed in an editor yet):
  VS Code:   code --install-extension "{vsix}" --force
             (--force also reinstalls the same version after an update), then reload the window.
  IntelliJ:  install the plugin LSP4IJ, then New Language Server -> Template -> "Import from custom
             template..." -> choose the folder {template}
  Others:    register `{interpreter} {START_FLAGS} {target / SERVER_NAME}` as a stdio language server for Markdown.

Way back:
  Uninstall the extension in VS Code (Extensions view, or `code --uninstall-extension act.act-id-links`),
  delete the language server entry in LSP4IJ, then delete the folder {target}.""")
    return 0


if __name__ == "__main__":
    try:
        from usage import count_script_run
        count_script_run(__file__)
    except ImportError:
        pass
    sys.exit(main())
