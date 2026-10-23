# Coding rules — Rust

summary: error handling, ownership and unsafe, edition and toolchain, tests

Rules for Rust projects built with Cargo. Group IDs (`CR-rust-<name>`) are stable and never reassigned; a
group whose purpose no longer holds gets a new ID and is listed as `retired:` in this header.

## `CR-rust-basics` — Error handling, ownership, unsafe

summary: no unwrap/expect in library code, no clone against the borrow checker, unsafe only with a SAFETY comment

- Library code never panics on a recoverable condition: no `unwrap()`/`expect()`, no indexing that can go
  out of bounds on external input, no `panic!` for bad arguments — return `Result` and let the caller
  decide. `unwrap()`/`expect()` are allowed in tests, in examples, and in `main` for startup failures;
  `expect("...")` then names the violated assumption, not the symptom.
- Define errors as typed values: an error `enum` (with `thiserror` if the project has it) in libraries,
  `anyhow` or `Box<dyn Error>` only in the binary's top layer. Every error states what failed and with
  what value; propagate with `?` and add context instead of discarding the cause.
- Do not add `.clone()` to silence the borrow checker. First try borrowing (`&T`, `&mut T`), a shorter
  lifetime, restructuring the code, or `Rc`/`Arc` where shared ownership is real; clone only when a
  separate owned value is what is meant.
- Take `&str`, `&[T]` and `&Path` in parameters instead of `&String`, `&Vec<T>`, `&PathBuf`.
- Every `unsafe` block carries a `// SAFETY:` comment stating the invariant that makes it sound, and
  encloses as little code as possible; every `unsafe fn` documents its contract under `# Safety`. Do not
  reach for `unsafe` to get around a compile error.
- Never ignore a `Result` or `#[must_use]` value with `let _ =` without a stated reason.
- Do not suppress warnings wholesale (`#![allow(warnings)]`); an `#[allow(clippy::...)]` names the lint
  and the reason.

## `CR-rust-edition-toolchain` — Edition, formatting, lint

summary: edition from Cargo.toml, rust-version, cargo fmt, clippy with warnings denied

- Read the edition (`edition = "2021"` or `"2024"`) and the minimum Rust version (`rust-version`) from
  `Cargo.toml` and write code that compiles under them: the 2024 edition needs Rust 1.85 or newer and
  changes, among other things, `unsafe` rules for `extern` blocks and the scope of temporaries; do not
  use syntax or library items newer than `rust-version` (`R-code-version`). Do not change the edition
  unasked.
- Format with `cargo fmt` (rustfmt) and lint with `cargo clippy --all-targets -- -D warnings` — the
  template's usual choice; run whatever the project has configured (see `R-code-tools`), and install
  nothing unasked.
- Commit `Cargo.lock` for binaries and, per Cargo's current advice, for libraries too; keep dependencies few and prefer the standard library where it
  suffices. Enable only the crate features that are used.

## `CR-rust-tests` — cargo test

summary: cargo test by default, unit tests beside the code, integration tests in tests/, doc tests

- `cargo test` is the template's usual runner; use the one the project has set up (`cargo nextest`, for
  example — see `R-code-tools`).
- Put unit tests in a `#[cfg(test)] mod tests` beside the code, integration tests in `tests/`, and keep
  examples in doc comments compiling as doc tests.
- Name tests after the expected behavior. Never use randomness without a fixed seed, and never wait with
  `thread::sleep`; wait on the actual condition instead.
