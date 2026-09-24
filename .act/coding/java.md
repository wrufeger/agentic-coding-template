# Coding rules — Java

summary: nullability, error handling, structure, toolchain, tests

Rules for Java projects. Group IDs (`CR-java-<name>`) are stable and never reassigned; a group
whose purpose no longer holds gets a new ID and is listed as `retired:` in this header.

## `CR-java-basics` — Nullability, error handling, established pitfalls

summary: explicit nullability, no raw types, correct exception handling, logging and SQL safety

- Make nullability explicit on fields, parameters and return types (JSpecify `@Nullable`/`@NonNull` or
  the alternative the project has fixed on) instead of leaving it implicit.
- No raw `Object`, no raw types on generics.
- No empty `catch` blocks and no `catch (Exception e)` without a concrete reason; use unchecked
  exceptions for programming errors and checked exceptions for expected, recoverable failures — the
  message must name what failed and with what.
- Manage resources exclusively through try-with-resources.
- Use `java.util.concurrent` (executors, `CompletableFuture`, concurrent collections) instead of manual
  `synchronized`/`wait`/`notify`.
- Log through SLF4J, parametrized (`log.info("user {} failed", id)`, never string concatenation) —
  see `R-safe-no-secret-log` for what never goes into a log line at all.
- Use `var` only where the type is obvious from the right-hand side, otherwise spell out the type.
- Return `Optional<T>` only as a method's return type for "possibly no result" — never as a field, a
  parameter, or inside a collection.
- Pitfalls: override `equals`/`hashCode` only together; use `java.time`, never `Date`/`Calendar`; use
  `BigDecimal` for money, never `float`/`double`; state `UTF_8` explicitly, never rely on the platform
  default; use only parametrized SQL, never string-concatenated queries; a plain loop may read better
  than forcing a Stream.
- Static analysis is the stack's standard — set it up, but run only what is installed; if a tool is
  missing, say so once and install nothing unasked.

## `CR-java-modern-idioms` — Records, sealed types, text blocks, virtual threads

summary: modern language features, requires Java 17 for most, Java 21 for virtual threads

- Use records for immutable data carriers (DTOs, value objects) instead of a manual class with
  getters, `equals`, `hashCode` and a constructor — requires Java 17 (records) or 16 (preview).
- Use sealed interfaces/classes with pattern matching (`switch` on type) instead of `instanceof` chains
  — requires Java 17.
- Use text blocks for multi-line strings (SQL, JSON templates) instead of concatenation — requires
  Java 17.
- Use virtual threads only where the runtime and every library on the path support them — requires
  Java 21.

## `CR-java-structure` — Package cut, immutability, constructor injection

summary: packages by domain, immutability as the default, constructor injection

- Cut packages by business domain, not by technical layer.
- Keep visibility as narrow as possible, fields `final`, no setter without a reason — immutability is
  the default and the best guard against concurrency bugs.
- Use constructor injection instead of field injection, even outside a DI container.

## `CR-java-toolchain` — Build and static analysis tools

summary: Maven or Gradle by default; static analysis whichever the project has set up

- Build with Maven or Gradle — the project decides which.
- Enforce formatting and static analysis in CI: Spotless or google-java-format for formatting, plus
  Checkstyle, SpotBugs, Error Prone or PMD — the template's usual choice; run whatever the project
  actually has set up (see `R-code-tools`).

## `CR-java-tests` — JUnit 5 with AssertJ by default

summary: JUnit 5/AssertJ by default, behavior-describing names, no unseeded randomness, no Thread.sleep

- Write tests with JUnit 5 and AssertJ — the template's usual choice; use the test framework the
  project actually has set up instead (see `R-code-tools`).
- Name tests after the expected behavior, not after the method under test.
- Never use randomness without a fixed seed.
- Never wait with `Thread.sleep`; wait on the actual condition instead.
