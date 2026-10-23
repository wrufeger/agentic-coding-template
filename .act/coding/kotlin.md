# Coding rules — Kotlin

summary: null safety, structured concurrency, data modelling, toolchain, tests

Rules for Kotlin projects (JVM, Android or multiplatform). Group IDs (`CR-kotlin-<name>`) are stable and
never reassigned; a group whose purpose no longer holds gets a new ID and is listed as `retired:` in this
header. A Kotlin project normally does not take the Java set; with mixed sources `init` ticks both, and where
only the odd Java call occurs, the interop rule below suffices.

## `CR-kotlin-basics` — Null safety, immutability, error handling

summary: no !!, val over var, specific exceptions, explicit API at boundaries, Java interop

- Never use `!!`. Handle nullability with `?.`, `?:`, `let`, an early `return`, or `requireNotNull(x) {
  "message" }` / `checkNotNull` where a missing value is a bug — the message names what was missing.
  `lateinit` only for framework-injected fields.
- Prefer `val` over `var`, read-only collections (`List`, `Map`) over mutable ones in signatures, and
  expressions (`when`, `if`) over mutation.
- Catch specific exception types; never swallow an exception or catch `Throwable`. Inside coroutines
  never catch `CancellationException` without rethrowing it. Use `Result` or a sealed type for expected
  failures instead of exceptions as control flow.
- Declare the type of public functions and properties explicitly, instead of relying on inference
  across a module boundary.
- Platform types from Java (`String!`) are not trusted: give them a nullable or non-null type at the
  point of entry, and annotate Kotlin APIs meant for Java callers (`@JvmStatic`, `@JvmOverloads`,
  `@Throws`) only where the Java side needs them.
- Use string templates, not concatenation, and `java.time` types (not `Date`/`Calendar`) on the JVM.
- Log through SLF4J or the project's logging facade with parametrized messages — see
  `R-safe-no-secret-log` for what never goes into a log line.

## `CR-kotlin-coroutines` — Structured concurrency

summary: no GlobalScope, scopes with a lifecycle, injected dispatchers, no runBlocking in production code

- Never launch work in `GlobalScope`. Start coroutines in a scope that owns their lifecycle
  (`coroutineScope`, `supervisorScope`, `viewModelScope`, a service's own `CoroutineScope`) so that
  failure and cancellation propagate.
- Do not call `runBlocking` in production code outside `main` and test bridges, and do not block a
  coroutine thread with `Thread.sleep` or blocking I/O: use `delay` and `withContext(Dispatchers.IO)`.
- Inject dispatchers as parameters instead of hard-coding `Dispatchers.IO`/`Default`, so tests can
  replace them. Expose `suspend` functions or `Flow` from APIs, not `Deferred` or callbacks.
- Use `kotlinx-coroutines-test` (`runTest`) for coroutine tests; never wait with `Thread.sleep`.

## `CR-kotlin-data-modeling` — data class, sealed types, value classes

summary: data class for values, sealed types for closed sets, copy over mutation

- Model plain values as `data class` with `val` properties and change them with `copy()`; do not put
  logic with side effects into a `data class`.
- Model closed sets of cases as `sealed interface`/`sealed class` and match them with an exhaustive
  `when` without an `else` branch, so adding a case breaks the build.
- Use `@JvmInline value class` for typed identifiers (ids, units) instead of bare `String`/`Long`; use
  `enum class` only for a fixed set without per-case data.

## `CR-kotlin-toolchain` — Build, formatting, static analysis, tests

summary: Gradle Kotlin DSL by default, ktlint and detekt, JUnit 5 or Kotest

- Read the Kotlin version from the build file or version catalog (`libs.versions.toml`) and use only
  language features that version supports (`R-code-version`): for example context parameters and
  guard conditions in `when` are newer than Kotlin 2.0.
- Build with Gradle and the Kotlin DSL (`build.gradle.kts`) — the template's usual choice; keep
  dependency versions in one place and use the Gradle wrapper the project ships.
- Format with ktlint (or `ktfmt`/Spotless) and analyze with detekt — the template's usual choice; run
  whatever the project actually has set up (see `R-code-tools`), and install nothing unasked.
- Write tests with JUnit 5 — the template's usual choice — optionally with Kotest assertions or
  MockK; use the framework the project has set up. Name tests after the expected behavior; never use
  randomness without a fixed seed.
