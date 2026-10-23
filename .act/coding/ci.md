# Coding rules — CI

summary: pinned actions, minimal permissions, injection-safe workflows, secrets, caching and concurrency for GitHub Actions and GitLab CI

Rules for pipeline definitions: GitHub Actions (`.github/workflows/*.yml`) and GitLab CI
(`.gitlab-ci.yml`). A pipeline runs with the project's secrets and write access, so these rules
extend the safety rules (`R-safe-no-secret-log`, `R-safe-no-secret-cli`, `R-safe-approval`). Group IDs
(`CR-ci-<name>`) are stable and never reassigned; a group whose purpose no longer holds gets a new ID
and is listed as `retired:` in this header.

## `CR-ci-supply-chain` — Pin what the pipeline runs

summary: actions and includes pinned to a commit SHA, minimal token permissions, automated updates

- GitHub: pin every third-party action to the full 40-character commit SHA, with the version as a
  trailing comment (`uses: actions/checkout@<sha> # v4.2.2`). A tag or branch can be moved by its owner
  and runs new code in your pipeline unseen. Check the SHA belongs to the upstream repository.
- GitLab: pin `include: project`/`remote` and CI images to a commit SHA or an image digest, never to
  `main` or `latest`.
- Set `permissions:` at the top of every workflow, to `contents: read`, and widen it per job only
  where a job needs it (`pull-requests: write`, `id-token: write`). Never leave the default token
  scope to the repository setting.
- Prefer short-lived OIDC credentials (`id-token: write`, GitLab `id_tokens:`) to long-lived cloud
  keys stored as secrets.
- Keep pins current with the project's updater (Dependabot or Renovate) rather than by hand; a pin
  nobody updates turns into an unpatched dependency.
- `actions/checkout` with `persist-credentials: false` unless a later step pushes.

## `CR-ci-injection` — Untrusted input never reaches a shell or a privileged run

summary: no event data inline in run:, no pull_request_target with fork code, no secrets for forks

- Never put `${{ github.event.* }}`, `github.head_ref`, an issue/PR title, body, branch name or commit
  message directly in a `run:` script — the text is substituted before the shell parses it and
  becomes code. Pass it through `env:` and use `"$VAR"`. GitLab expands variables in the shell at run time,
  so the danger there is unquoted use: quote `"$CI_COMMIT_MESSAGE"`, `"$CI_MERGE_REQUEST_TITLE"` and branch
  names inside `script:`, never `eval` or splice them.
- `pull_request_target` and `workflow_run` run in the base repository's context with secrets and a
  writable token. Never check out or run the pull request's head
  (`ref: ${{ github.event.pull_request.head.sha }}`) there, and never run its scripts or build step.
  Use plain `pull_request` for anything that builds contributed code.
- Fork pull requests get no secrets: do not design a check that needs one on `pull_request`; split
  it into an unprivileged build and a separate, reviewed privileged step.
- A deploy or release job runs only on protected branches and tags (`if:` on the ref, GitLab
  `rules:` with `$CI_COMMIT_REF_PROTECTED`), behind the environment's required approval.

## `CR-ci-secrets` — Secrets stay out of logs, arguments and artifacts

summary: secrets via secret store and environment, masked, never echoed, never in cache or artifacts

- Take secrets from the platform's secret store (GitHub `secrets`/environment secrets, GitLab masked
  and protected CI/CD variables) and hand them to a step through `env:`, not as an argument.
- Never `echo` a secret or a value derived from it, and no `set -x`/CI debug trace in a job that has
  secrets. Mask a computed value with `::add-mask::` before it is printed.
- No secret in an artifact, cache, build argument (`docker build --build-arg`) or uploaded report;
  those outlive the job and are readable by more people than the secret.
- A secret that leaked into a log is treated as compromised and rotated, not just deleted from the log.

## `CR-ci-runtime` — Caching, concurrency, timeouts

summary: lockfile-keyed caches, concurrency groups, job timeouts, the same checks as local

- Key a cache on the lockfile hash (`hashFiles('**/package-lock.json')`, GitLab `cache:key:files`),
  never on a fixed string; cache downloaded dependencies, not build output of untrusted branches.
- Set `concurrency:` with `cancel-in-progress: true` for pull request checks; never cancel a running
  deploy or release — give those a group without cancellation. GitLab: `interruptible: true` and
  `resource_group` for deploys.
- Set `timeout-minutes:` (GitLab `timeout:`) on every job; the platform default is hours.
- CI runs the same commands the project documents for local use (`docs/ai/config.md`, `R-code-tools`)
  — no check that exists only in the pipeline. A failing check is fixed in the code, not skipped or
  set to `continue-on-error` (`R-code-checks-intact`).
- GitLab: use `rules:`, not the deprecated `only:`/`except:`.
