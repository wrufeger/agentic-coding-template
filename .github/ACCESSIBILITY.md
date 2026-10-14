<!-- act:template-community -->
# Accessibility

Last reviewed: 2026-10-14.

## Goal

The template is operated through conversation: you talk to an AI assistant, skills react to plain sentences
("hand over", "commit", "fetch feedback"), open questions arrive as files in the inbox, and answers are short. In
principle this suits voice input (dictation, operating-system voice control) and screen readers. The goal is that
everything needed to work on a project built on the template can be done without a mouse and without reading
graphics.

This is a goal, not a promise. No session has yet been run with voice input alone or with a screen reader, so
nothing below is claimed to work.

## Supported environments

| Environment | Status |
| :--- | :--- |
| Voice input (Windows Voice Access, dictation, macOS Voice Control) with an AI assistant | not tested |
| Screen reader in the terminal (for example NVDA, VoiceOver) | not tested |
| Screen reader with the documentation site | not tested |
| Keyboard-only operation of the AI tool | not tested |
| Screen magnification and high-contrast settings | not tested |

A status changes only after someone has tried it; the entry then names the date and the tool.

## Known barriers

These are places that ask for eyes or hands, found by reading the template, not by user testing:

- Permission prompts of the AI tool are answered by choosing an entry with the keyboard.
- The status line shows information in a compact visual form.
- Tables in the board (`docs/ai/board.md`) and in the rules are hard to follow by ear.
- Mermaid diagrams in the documentation have no text equivalent beyond the surrounding prose.
- The documentation site has never been checked for accessibility.

The `act-a11y` skill checks the accessibility of the code of a project built on the template. It does not cover
the template's own usability described here.

## What we expect from contributors

- Write text so it works when read aloud: no meaning carried by color, position or an image alone.
- Give every diagram a short text description next to it.
- Prefer lists and short sentences over wide tables where the content allows.
- Do not add a step that can only be done with a pointing device.
- If you tried the template with voice input or a screen reader, say which tool and version you used.

## Reporting a barrier

1. **Recommended:** type `/act-feedback <text>` in the AI assistant of a project built on the template (or
   `feedback: <text>`). The text reaches the maintainer exactly as written.
2. Otherwise open an issue in this repository and describe what you tried, the tool you used and where it stopped.

Never include secrets or real personal data. See [CONTRIBUTING.md](CONTRIBUTING.md) for the general process.

## Responsibility

The maintainer of the template reads reports and keeps this page current. Barriers are fixed in the order they
block work; a reported barrier is listed here until it is fixed or ruled out.
