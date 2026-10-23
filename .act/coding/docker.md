# Coding rules — Docker

summary: pinned base images, non-root and multi-stage builds, build context and secrets, Compose, hadolint

Rules for Dockerfiles and Compose files. Group IDs (`CR-docker-<name>`) are stable and never
reassigned; a group whose purpose no longer holds gets a new ID and is listed as `retired:` in this
header.

## `CR-docker-image` — Pinned base image, small and multi-stage

summary: tag plus digest, no latest, multi-stage build, one process per container, layer order and cleanup

- Pin the base image by tag and digest (`FROM python:3.12-slim@sha256:...`); never `latest` or a bare
  major-version tag alone. Take the language version from the project files (`R-code-version`), not from
  habit, and update the digest on purpose, not by rebuilding.
- Build in stages: compilers, dev dependencies and caches stay in a `builder` stage; the last stage copies
  only the result (`COPY --from=builder`) into a slim or distroless base.
- Order layers by how rarely they change: copy the dependency manifest and install first, the source last,
  so a code change does not reinstall everything. Do the install and its cleanup in one `RUN`
  (`apt-get update && apt-get install -y --no-install-recommends ... && rm -rf /var/lib/apt/lists/*`), since a
  later `rm` does not shrink an earlier layer.
- Prefer `COPY` to `ADD`; use the exec form for `CMD` and `ENTRYPOINT` (`["python", "app.py"]`) so signals
  reach the program; one main process per container.

## `CR-docker-security` — Non-root user, no secrets in layers

summary: USER set, .dockerignore, build secrets instead of ARG/ENV, no credentials in the image

- Run as a non-root user: create it (`RUN useradd --system --uid 10001 app`) and set `USER` before `CMD`;
  copy files with `--chown`. Do not run a service as root "to make it work".
- Keep a `.dockerignore` next to the Dockerfile that excludes at least `.git`, `.env*`, dependency folders
  (`node_modules`, `.venv`), build output and local data, so none of it reaches the build context or a layer.
- A secret never goes into `ARG`, `ENV`, `COPY` or a `RUN` argument: each stays readable in the image
  history (`docker history`). Use a BuildKit secret mount (`RUN --mount=type=secret,id=name ...`, passed with
  `--secret`) for build time and the runtime environment or a mounted file for run time (`R-safe-no-secret-cli`).
- Do not bake configuration that differs per environment into the image; pass it in at run time.

## `CR-docker-compose` — Compose files

summary: no version key, pinned images, named volumes, env file out of version control, healthy dependencies

- Use the Compose Specification (Docker Compose v2, `docker compose`): leave out the obsolete top-level
  `version:` key. Check the installed version with `docker compose version`.
- Pin every `image:` as above; no `latest`. Name volumes instead of anonymous ones, and do not bind-mount the
  Docker socket (`/var/run/docker.sock`) into a container.
- Keep values and secrets in an `.env` file or `secrets:`, never in `compose.yaml`; commit only an
  `.env.example`. Publish only the ports that are needed, bound to `127.0.0.1` unless the service is meant to be
  reachable from outside. A host port clashes with the owner's server — see `R-safe-dev-server`.
- Make start order real: `depends_on` with `condition: service_healthy` and a `healthcheck`, not a sleep.

## `CR-docker-toolchain` — Lint and build checks

summary: hadolint for Dockerfiles, docker compose config for Compose, or what the project has set up

- `hadolint` is the template's usual Dockerfile linter; validate Compose files with `docker compose config
  --quiet`. Run what the project has configured and install nothing unasked (`R-code-tools`).
- Build with BuildKit (the default in current Docker) and verify the result by running the image once, not
  only by a green build.
