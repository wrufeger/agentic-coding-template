# Clickable entry ids

Detail page for the optional editor support that turns entry ids in Markdown files into links. Not
loaded by a session start and tied to no rule: read it when a person wants ids such as `T12`
clickable in their editor. Nothing here applies to a project whose people do not install it.

## What it does

In a Markdown file, every id of the form letter `B`, `Q`, `T` or `U` plus digits (and an optional
trailing letter) becomes:

- a **link** (Ctrl+click in VS Code, click in IntelliJ),
- a **go to definition** target (F12 in VS Code, Ctrl+B in IntelliJ),
- a **hover** showing `<id> — <title>` and `Status: <status>`.

An id is linked only when an entry file exists for it under `docs/ai/`, searched at each request in this
order: a single file `<id>-*.md` or `<id>.md` in `inbox/`, `work/tasks/` or `work/backlog/`; the same
form in `work/archive/`; then a section `## <id>` (with its `<a id="<id>"></a>` anchor) in a collection
file in `work/archive/`, newest file first. An id without a file stays plain text — so does the id of an
entry deleted under `done-entries: delete`, whose text Git history keeps. There is no stored
index, so a link is never out of date. The project root is the open folder that contains `docs/ai/`.

## Install, once per machine

```
python .act/scripts/id_links_install.py
```

It writes only under `~/.act/id-links/` (`~` is your home folder; on Windows `%USERPROFILE%`): a copy
of the language server and its helper, the VS Code extension as a `.vsix` file, and an import
template for IntelliJ. A second run overwrites the same files. It installs nothing into an editor and
starts no editor; it prints the next steps below. `--home <dir>` uses another folder instead of `~`.

Then, per editor:

- **VS Code:** `code --install-extension "<path of the .vsix printed by the command>" --force`. The
  `code` command must be on the path. `--force` matters after an update, when the version is the same.
- **IntelliJ-based IDEs:** install the plugin **LSP4IJ** from the Marketplace. Then in the language
  server view choose New Language Server, Template, "Import from custom template...", and select the
  folder `~/.act/id-links/lsp4ij`.
- **Other editors with language server support** (Neovim, Zed, Helix, Sublime, Emacs ...): register
  the copy `~/.act/id-links/id_links_lsp.py` as a stdio language server (`python -I -S <path>`) for
  Markdown files, in that editor's own configuration.

## Trust boundary

- The editor starts only the copy under `~/.act/id-links/`, never a file inside a repository. Pointing
  an editor at a script in the repo would run the code of any clone you open.
- The VS Code extension declares that it does not support untrusted workspaces, so it runs only in
  folders you marked as trusted.
- The editor starts the base Python interpreter, not one from a virtual environment in a repository
  (the installer says so when it replaced one), with `-I -S`: the editor's `PYTHONPATH`/`PYTHONHOME`
  and `.pth` files have no effect.
- The server and the extension only read under `docs/ai/`: file names, the first heading and header
  lines of single entry files, and whole collection files in `work/archive/` (to find sections). They
  write nothing, use no network and start no other process.

## After `act-update`

`act-update` replaces the sources in the project (`.act/scripts/`, `.act/ide/`) but never touches
`~/.act/id-links/`. Run `python .act/scripts/id_links_install.py` again to refresh the copies, then
install the new `.vsix` again with the printed `code --install-extension "<vsix>" --force` (the version
may be unchanged, so without `--force` VS Code keeps the old one) and reload the window.

## Remove

Uninstall the extension in VS Code, delete the language server entry in IntelliJ (LSP4IJ), remove the
entry from any other editor's configuration, then delete the folder `~/.act/id-links/`. Nothing else
in the project is affected.

## Limits

- Only ids that have an entry file get a link; a mention of an id with no file stays plain text.
- Commit messages in the git log are not covered; an editor's language server only sees files.
- IntelliJ needs the LSP4IJ plugin; without it nothing is clickable there.
- The search rules exist twice, in Python (server) and in JavaScript (VS Code extension), and are kept
  identical.
