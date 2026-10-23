# Coding rules — C++

summary: language standard, RAII and ownership, const and Rule of Zero, warnings and sanitizers, CMake and tests

Rules for C++ only; they do not apply to C, whose code is written with manual memory management and
C idioms and has its own set. Group IDs (`CR-cpp-<name>`) are stable and never reassigned; a group whose
purpose no longer holds gets a new ID and is listed as `retired:` in this header.

## `CR-cpp-basics` — Standard, build and warnings

summary: standard from the build, features gated by it, strict warnings, clang-tidy, CMake

- Take the standard from the build configuration (`CMAKE_CXX_STANDARD`, `-std=c++17`, `20`, `23`) and
  use nothing newer. Per standard: `std::optional`, `std::variant`, `std::string_view` and structured
  bindings are C++17; concepts, ranges, `std::span` and `std::format` are C++20 (`std::format` also
  needs a recent standard library); `std::expected` and `std::print` are C++23. Without a configured
  standard, assume C++17.
- Take warnings seriously (`-Wall -Wextra -Wpedantic`; MSVC `/W4`): fix one in the code, do not silence
  it with a cast or a pragma. Suggest `-Werror` (`/WX`) once; never set build flags unasked (`R-code-tools`).
- Run `clang-tidy` as the usual linter and `clang-format` as the usual formatter, or whatever the
  project has configured (`R-code-tools`). CMake is the usual build system; use the one the project
  has (Make, Meson, Bazel) and install none unasked.
- Do not write C into C++: no `malloc`/`free`, C-style casts, `NULL` (use `nullptr`), or raw arrays
  where `std::array`, `std::vector` or `std::string` fit.

## `CR-cpp-ownership` — RAII, no raw new and delete

summary: resources owned by objects, smart pointers, Rule of Zero

- Every resource (memory, file, lock, handle) is owned by an object that releases it in its destructor
  (RAII). No raw `new`/`delete`: use `std::make_unique` (default) or `std::make_shared` (only for
  genuinely shared ownership), containers, or `std::lock_guard`/`std::scoped_lock`.
- A raw pointer or reference is non-owning and borrowed; never `delete` through it and never keep it
  beyond the owner's lifetime. Do not return a reference or `std::string_view` to a local or temporary.
- Rule of Zero: a class that holds only RAII members declares none of the special member functions. If
  one of destructor, copy or move must be written, define or delete all five (Rule of Five); mark move
  operations `noexcept`.
- Do not let exceptions cross a C interface or leave a thread unhandled; follow the project's existing
  error style (exceptions or `std::expected`/error codes) instead of mixing both.

## `CR-cpp-correctness` — const, types and undefined behavior

summary: const by default, explicit constructors, no unchecked casts, container invalidation

- `const` by default for variables, member functions and parameters; pass large read-only arguments by
  `const&`, small ones by value. Mark single-argument constructors `explicit` and overrides `override`.
- Use `static_cast` and friends only where needed; no C-style casts, and never `reinterpret_cast` or a
  cast that removes `const` without a comment saying why it is safe.
- Signed overflow, out-of-range `operator[]`, use after move and use of an iterator after the container
  changed are undefined behavior: use `.at()` or check bounds where input is untrusted, and do not
  reuse a moved-from object except to assign to it.
- Initialize with braces or at declaration; prefer `enum class` over plain `enum`.

## `CR-cpp-tests` — Tests under sanitizers

summary: GoogleTest or Catch2 via CTest, ASan and UBSan in the test run

- Use the test framework the project has set up (GoogleTest or Catch2 are the usual choices), run
  through `ctest`; do not add one unasked.
- Run the suite at least once with `-fsanitize=address,undefined -fno-omit-frame-pointer`; a sanitizer
  report is a failure, never suppressed to get green (`R-code-checks-intact`).
