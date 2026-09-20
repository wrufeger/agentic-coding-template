# Coding rules — C#

summary: nullable context, async conventions, error handling, analyzers, DI, library code

Rules for C# projects. Group IDs (`CR-csharp-<name>`) are stable and never reassigned; a group
whose purpose no longer holds gets a new ID and is listed as `retired:` in this header.

## `CR-csharp-basics` — Nullable context, async, error handling, analyzers

summary: nullable enabled, async suffix, no async void, no blocking on tasks, using, exceptions

- Keep the nullable context (`<Nullable>enable</Nullable>`) on project-wide; do not suppress the
  warnings it produces.
- Name asynchronous methods with the `Async` suffix and return `Task`/`Task<T>`.
- Never use `async void` outside event handlers — use `async Task`, otherwise exceptions are
  swallowed.
- Avoid `.Result`/`.Wait()` on tasks; blocking on a task this way risks a deadlock in synchronous
  contexts.
- Manage every `IDisposable` resource exclusively through `using`/`await using`.
- Use exceptions for exceptional cases, not for regular control flow — consider a return type
  (`Result<T>`/`bool`) for expected failure cases; wherever an exception is thrown, its message
  names what failed and with what.
- Run `dotnet format` and the analyzer rules (`.editorconfig` section `dotnet_diagnostic`) as the
  stack's standard linting/static analysis; set them up in every project, run what is installed.

## `CR-csharp-conventions` — var, records, one type per file

summary: var only for an obvious type, records for value objects, one public type per file

- Use `var` only when the type is obvious from the right-hand side, an explicit type otherwise.
- Use records for immutable value objects/DTOs, classes for objects with identity and behavior.
- One public type per file, with the file name matching the type name.

## `CR-csharp-dependency-injection` — Constructor injection

summary: constructor injection, no service locator

- Inject dependencies through the constructor; no hidden service-locator access.

## `CR-csharp-library-code` — ConfigureAwait in library code

summary: ConfigureAwait(false) in code without a UI context

- Use `ConfigureAwait(false)` in library code that has no dependency on a UI context.
