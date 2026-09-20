# Coding rules — PHP

summary: strict types, PSR-12/PSR-4, exceptions, prepared statements, toolchain

Rules for PHP projects (8.x and later). Group IDs (`CR-php-<name>`) are stable and never reassigned; a
group whose purpose no longer holds gets a new ID and is listed as `retired:` in this header.

## `CR-php-basics` — Strict types, safe errors, safe queries

summary: strict_types, PSR-12/PSR-4, typed methods, exceptions, PDO, production errors, static analysis

- Put `declare(strict_types=1);` as the first statement in every PHP file.
- Follow PSR-12 for formatting (4-space indentation) and PSR-4 for namespaces, one namespace per
  Composer autoload root.
- Keep one class per file, with the filename matching the class name.
- Manage dependencies through Composer only; never include a library by hand.
- Declare parameter and return types on every public method. Use `mixed` only with a comment justifying
  it, and mark nullable types (`?Type`) explicitly instead of falling back to an implicit `null`.
- Throw exceptions instead of returning `false` or an error code. Define one exception class per error
  domain rather than throwing a blanket `\Exception`, and let the message name what failed and with
  what — a database exception names the query or table, a validation exception names the field and the
  value it rejected.
- Keep business logic out of templates (Blade, Twig, plain PHP templates); templates render, they don't
  decide.
- Access the database only through PDO with prepared statements; never build SQL by concatenating
  values into the query string.
- Use `===`/`!==` wherever type equality is meant, not the loose operators.
- Turn `display_errors` off in production; errors go to the log, not into the response.
- Static analysis is the stack's standard and belongs in the project. Run what is installed, install
  nothing unasked.

## `CR-php-conventions` — Closures over global callbacks

summary: arrow functions and closures instead of global callback functions

- Use arrow functions/closures instead of global callback functions.

## `CR-php-toolchain` — Formatter and static analysis tooling

summary: PHP-CS-Fixer or PHP_CodeSniffer, PHPStan or Psalm

- PHP-CS-Fixer or PHP_CodeSniffer, configured for PSR-12.
- PHPStan or Psalm for static analysis.
