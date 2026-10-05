---
name: act-check-translations
description: Check a project's translation files for completeness and consistency - missing, extra and empty keys, placeholder mismatches, keys used in code but not defined, defined but unused - and work through the findings. Use when asked to check translations or i18n, whether all languages are complete, or after adding a language or new UI text.
---

# Check translations

Checks the project's language files against each other and against the source code. Code only: no
browser, no running app — what a translated page looks like in the browser is not covered.

1. **Run the check.** `python .act/scripts/i18n_check.py` (add `--json` to process the result,
   `--base <locale>` if the source language is not `en`, `--no-code` to skip the code scan, `--root`
   for a sub-project). It finds JSON and simple YAML files in folders named `locales`, `i18n`, `lang`,
   `messages`, `translations` or `l10n`, one file per locale or one folder per locale. No translation
   files found: say so and stop — do not guess other places.
2. **Confirm the base locale.** The script takes `en`, else the largest file. If the project's source
   language is another one, re-run with `--base`; a wrong base turns every finding around.
3. **Judge the findings**, heaviest first:
   - `placeholder-mismatch` and `used-undefined` (error): a broken placeholder shows `{name}` to the user
     or throws; an undefined key shows its raw key. Fix first.
   - `missing`, `extra`, `empty` (warning): a missing key falls back to the base language or shows the
     key; `extra` is usually a leftover from a rename or a typo in the key; `empty` is an unfinished
     translation.
   - `unused` (info): best effort — keys built at runtime (`t(\`menu.${name}\`)`, `'menu.' + name`) are
     only guessed from their literal prefix, so check each one by hand before deleting anything.
   - `parse-error`: broken JSON/YAML; the file is skipped, the other findings for that locale are
     incomplete until it is fixed.
4. **List what you propose** — key, locale, fix — and ask. Never translate on your own: a missing
   translation needs the human's yes and, for a language you cannot vouch for, their review. Renames
   and deletions of keys touch the source code too; name those places.
5. **Fix what is approved**, re-run the script, show the before/after counts, then `act-commit`.

## Limits

- Heuristics: the call patterns recognized are `t('k')`, `$t("k")`, `i18n.t`, `__('k')`, `trans('k')`,
  `gettext('k')`. A project with its own wrapper function is not seen — say so rather than reporting
  everything as unused.
- YAML: only the simple `key: value` form with nesting by indentation; anchors, flow style and
  multi-document files are not understood (reported as `parse-error`).
- Plural and gender forms are compared key by key; whether a language has the right number of plural
  forms is a linguistic question the script does not answer.
- No judgment of translation quality, tone or terminology.
