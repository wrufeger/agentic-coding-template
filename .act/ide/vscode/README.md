# ACT ID Links (VS Code)

Makes entry ids such as `T12` clickable in Markdown files: a link, go to definition and a hover with title and
status. An id becomes a link only when an entry file exists for it under `docs/ai/` (inbox, tasks, backlog,
archive, archive collection files).

- Plain JavaScript, no npm, no dependencies, no build step. It starts no server and no other process.
- Read-only: it lists folders and reads entry files under `docs/ai/`; it writes nothing and uses no network.
- Source: `extension.js.txt` (the `.txt` keeps linters that scan `.act/` from checking it). The install command
  packs it as `extension.js` into the `.vsix` together with `package.json`.
- Install: run `python .act/scripts/id_links_install.py`. It builds the `.vsix` under `~/.act/id-links/` and prints
  the commands for the editor; run them once per machine. Details and the way back are in
  `.act/rules/topics/id-links.md`.
- Trust boundary: the extension declares `untrustedWorkspaces.supported: false`, so VS Code runs it only in
  folders you marked as trusted. Install the extension from the copy the install command makes, never from a
  file inside a repository you have just cloned.
- Remove: uninstall the extension in VS Code.
