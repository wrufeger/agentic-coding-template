<!-- act:template-community -->
# Security Policy

## Supported versions

Security fixes go into the latest release line, currently 2.x (see [CHANGELOG.md](../CHANGELOG.md)). Older lines are
not patched; update with `act-update`.

## Reporting a vulnerability

**Do not open a public issue.** Use one of these:

1. **From a project built on the template (recommended, fastest):** type `/act-feedback <text>` in your AI
   assistant (or `feedback: <text>`). The text goes privately and exactly as written to the maintainer, together
   with the template commit it runs on. Name a reply address in the same request if you want an answer.
2. GitHub's private reporting: the **Security** tab of this repository, then **Report a vulnerability**
   (https://github.com/wrufeger/agentic-coding-template/security/advisories/new).
3. If neither is available to you, e-mail wolfgang@rufeger.de.

Please include the template version (`.act/VERSION`), your AI tool, your operating system, and the steps to
reproduce. Leave out real secrets and personal data.

## What counts

- Any way around one of the template's safety checks: hooks and the checks listed in `docs/ai/config.md` § Checks,
  such as `secret-scan`, `secret-read`, `git-reset-hard`, `git-discard`, `git-metadata-guard`, `recursive-delete`,
  `template-write-guard`, `worker-write-scope`, `worker-docs-ai`, `worker-git-write`.
- `update.py`, `init.py` or `adopt.py` executing code that came from a freshly fetched ref, instead of only
  reading it.
- Secrets or personal data ending up in logs, commits, feedback messages or generated files.
- Writing into git metadata (hooks, repository config) or outside the project without the owner's action.

Ordinary bugs and rule suggestions belong in a normal issue.

## What to expect

This is a one-person project. You get an acknowledgement within 7 days and a first assessment soon after. Fixes
ship in a release and are listed under `Security` in the changelog; you are named there if you wish. Please keep
the details private until a fix is out.
