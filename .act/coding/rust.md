# Coding rules — Rust

summary: error handling, numbers, ownership and unsafe, async, edition and toolchain, tests

Rules for Rust projects built with Cargo. Group IDs (`CR-rust-<name>`) are stable and never reassigned; a
group whose purpose no longer holds gets a new ID and is listed as `retired:` in this header.

## `CR-rust-basics` — Error handling, numbers, ownership, unsafe

summary: no unwrap/expect in libraries, checked conversions and overflow, no needless clone, SAFETY comments

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
- Narrowing or sign-changing `as` truncates or wraps silently: use `TryFrom`/`try_into()` and handle the
  error, `From`/`into()` to widen; `as` only on a proven range, with a comment. The Clippy lint for it
  (`cast_possible_truncation`) is in `pedantic`, so `-D warnings` misses it.
- Arithmetic on outside values (input, files, network, sizes, offsets) handles overflow: `checked_*` with
  an error, or `saturating_*`/`wrapping_*` by intent; release builds wrap silently unless the profile sets
  `overflow-checks = true`.

## `CR-rust-async` — Async code

summary: no blocking in tasks, project runtime, cancel-safe select!, bounded channels, async fn in traits

- In async code, never block a task: no `std::fs`/`std::net`, blocking HTTP client, `std::thread::sleep`
  or long CPU work in an `async fn`; use the async variant (`tokio::fs`, `tokio::time::sleep`) or the
  blocking pool (`spawn_blocking`). No default lint catches this.
- The runtime and its `features` are a project decision: read them from `Cargo.toml` (`tokio`,
  `async-std`, `smol` …), write for that runtime, add no second one, enable no new feature unasked.
- `select!` in a loop drops the futures of the branches that lost, on every turn: use only futures
  documented as cancel-safe there, or create the future once before the loop, pin it and poll it by
  `&mut`; else half-read data is lost.
- Channels between tasks are bounded (`tokio::sync::mpsc::channel(n)`, not std's `mpsc::channel()`) so a
  slow consumer pushes back; unbounded only where the producer is bounded by construction, with a comment
  why.
- With `rust-version` 1.75 or newer, write `async fn` in a trait directly instead of `async_trait`, unless
  the trait is used as `dyn Trait`; in a public trait (rustc's `async_fn_in_trait` lint warns there) or
  where callers need a `Send` future, declare `fn name(&self) -> impl Future<Output = T> + Send`. Keep
  `async_trait` where the project needs it for `dyn`. Below 1.75 this does not apply (`R-code-version`).

## `CR-rust-edition-toolchain` — Edition, formatting, lint

summary: edition and rust-version from Cargo.toml, project lints, MSRV-fit dependencies, fmt, clippy

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
- Follow the project's lint configuration (`[lints]`/`[workspace.lints]` in `Cargo.toml`, `clippy.toml`,
  crate-level `#![deny(...)]`); never loosen or extend it unasked (`R-code-checks-intact`). A new
  dependency comes in a version whose own `rust-version` fits the project's: `resolver = "3"` (the default
  from edition 2024) picks such versions; otherwise check it, and never raise the project's
  `rust-version` to fit one.

## `CR-rust-tests` — cargo test

summary: cargo test by default, unit tests beside the code, integration tests in tests/, doc tests

- `cargo test` is the template's usual runner; use the one the project has set up (`cargo nextest`, for
  example — see `R-code-tools`).
- Put unit tests in a `#[cfg(test)] mod tests` beside the code, integration tests in `tests/`, and keep
  examples in doc comments compiling as doc tests.
- Name tests after the expected behavior. Never use randomness without a fixed seed, and never wait with
  `thread::sleep`; wait on the actual condition instead.
