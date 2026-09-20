# Coding rules — Go

summary: strict error checking, static analysis tooling, package design

Rules for Go projects. Group IDs (`CR-go-<name>`) are stable and never reassigned; a group
whose purpose no longer holds gets a new ID and is listed as `retired:` in this header.

## `CR-go-basics` — Error handling, formatting, static analysis

summary: check and wrap errors, format with gofmt, run vet/staticcheck, avoid panics and leaks

- Format every file with `gofmt`/`goimports` before committing; no hand-tuned deviation from either.
- Check an error immediately after the call that returned it (`if err != nil`) instead of collecting
  errors for later, and never discard a return value with `_` when it comes with an unchecked error.
- Wrap errors with `%w` (`fmt.Errorf("...: %w", err)`) so `errors.Is`/`errors.As` keep working further
  up the call chain; never lose or flatten the underlying error.
- Run `go vet` and `staticcheck` in CI as the stack's standard static analysis — set them up, but run
  only what is installed; if a tool is missing, say so once and install nothing unasked.
- No panics in library code for expected failure cases; panic only for genuine programming errors.
- `context.Context` is the first parameter of any function that must propagate cancellation, a
  deadline, or request-scoped values.
- Every goroutine has a visible lifecycle end (`WaitGroup` or context cancellation) — a goroutine
  with no way to stop is a leak.
- Synchronize state shared between goroutines through channels or explicit locks, never silently.

## `CR-go-package-design` — Small interfaces, no grab-bag packages

summary: interfaces defined by the consumer, packages named and cut by domain

- Define interfaces on the consumer side (small, often one or two methods), not upfront by the
  provider that implements them.
- Give packages short, meaningful names cut by domain; no `util`/`common` grab-bag package without a
  real subject of its own.
