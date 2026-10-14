<!-- act:template-community -->
<!--
A bug report or a feature idea does not need a pull request: /act-feedback <text> in your AI assistant is the
recommended and fastest way. Pull requests make sense for larger changes and for corrections you have worked
out; describe a larger change with /act-feedback or an issue first.
-->

## What and why

<!-- What does this change, and why? Keep it short. -->

## Linked issue

<!-- Closes #... (larger changes should be agreed via /act-feedback or an issue first) -->

## How it was checked

<!-- Evidence: a real run with output, a throwaway repo, a screenshot. "It compiles" is not enough for a script change. -->

## Checklist

- [ ] Everything under `.act/` is in English
- [ ] `CHANGELOG.md` § `[Unreleased]` has an entry for any visible change
- [ ] `python .act/scripts/manifest.py --write` run after changes under `.act/`
- [ ] `python .act/scripts/script_docs.py` run after script changes
- [ ] No secrets and no real personal data in the diff
