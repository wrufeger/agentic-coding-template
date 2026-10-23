# Coding rules — C

summary: language standard, memory ownership and buffers, checked return values, undefined behavior, warnings and sanitizers

Rules for C only; they do not apply to C++, whose idioms differ (RAII, containers, exceptions) and have
their own set. Group IDs (`CR-c-<name>`) are stable and never reassigned; a group whose purpose no longer
holds gets a new ID and is listed as `retired:` in this header.

## `CR-c-basics` — Standard, build and warnings

summary: fixed language standard, strict warnings as errors, clang-tidy, build system as configured

- Take the C standard from the build configuration (`-std=c11`, `c17`, `c23`, or `CMAKE_C_STANDARD`) and
  use nothing newer: `nullptr`, `constexpr`, `bool` as a keyword and `typeof` are C23 only; `_Generic`,
  `_Static_assert` and `<threads.h>` need C11. Without a configured standard, assume C11.
- Never write C++ habits into C: no cast of the `malloc` result, no `bool`/`true` without `<stdbool.h>`
  before C23, and declare parameterless functions as `f(void)`, not `f()`.
- Take warnings seriously (`-Wall -Wextra`; MSVC `/W4`): fix one in the code, do not silence it with a
  cast or a pragma. Suggest `-Werror` (`/WX`) once; never set build flags unasked (`R-code-tools`).
- Run `clang-tidy` as the usual linter and `clang-format` as the usual formatter, or whatever the project
  has configured (`R-code-tools`); keep to the build system it already has (CMake, Make, Meson) and
  install none unasked.

## `CR-c-memory` — Buffers and ownership

summary: every buffer carries its size, one owner per allocation, no unbounded string functions

- Pass a buffer together with its size and check the size before writing; never `gets`, `strcpy`,
  `strcat` or `sprintf` into a fixed buffer — use `snprintf` and `memcpy` with an explicit length, and
  terminate strings yourself where the function does not (`strncpy`).
- Every `malloc`/`calloc`/`realloc` result is checked for `NULL` before use. `realloc` goes into a
  temporary, so the old pointer is not lost on failure.
- Compute allocation sizes from the target (`malloc(n * sizeof *p)`), and check the multiplication for
  overflow first (`calloc` does it for you).
- Each allocation has exactly one owner, named in a comment or the function's header comment: who frees
  it, and who may only borrow it. Free once, set the pointer to `NULL` afterwards where it stays in
  scope, and release on every error path (a single `goto cleanup` exit is the accepted idiom).
- Never return or store a pointer to a local (stack) variable.

## `CR-c-correctness` — Return values and undefined behavior

summary: no ignored errors, integer overflow, signed/unsigned and strict aliasing

- Check the return value of every call that can fail (`fopen`, `fread`, `fwrite`, `fclose`, `snprintf`
  truncation, `read`/`write`, `pthread_*`); an error message names the call, its argument and `errno`
  (`strerror`).
- Signed integer overflow is undefined behavior: validate operands before the arithmetic, not after.
  Use `size_t` for sizes and indices, and never compare signed with unsigned without an explicit
  conversion. Check shift counts, division by zero and `INT_MIN / -1`.
- Do not read an object through a pointer of an incompatible type (strict aliasing) or an uninitialized
  variable; use `memcpy` for type punning and initialize at declaration.
- Make unused parameters and switch fallthrough explicit (`(void)x;`, a comment, or `[[fallthrough]]`
  in C23), not silent.

## `CR-c-tests` — Tests under sanitizers

summary: tests run with ASan and UBSan, test runner as configured

- Run the test suite at least once with `-fsanitize=address,undefined -fno-omit-frame-pointer` (MSVC:
  `/fsanitize=address`); a sanitizer report is a failure, never suppressed to get green
  (`R-code-checks-intact`).
- Use the test framework the project has set up (Unity, Check, CMocka, or plain `ctest`); do not add one
  unasked. Cover the error path of each allocation or I/O call, not only the happy path.
