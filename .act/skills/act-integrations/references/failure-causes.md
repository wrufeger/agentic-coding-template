# Causes and fixes for missing or failing access (step 4)

Read from step 4 of `SKILL.md` when the check shows a missing token, a too small scope, an unconfirmed host, a plain http address, or an HTTP error.

Causes and fixes, by what the check shows:

   - No token: the variable for the host — `GITHUB_TOKEN` (or `GH_TOKEN`) for GitHub, `GITLAB_TOKEN`
     for GitLab — in the process environment or in `.env` in the project root. `forge.py` reads
     `.env` (only these names), Claude Code itself does not. `.env` belongs in `.gitignore`; the
     check notes it when it does not. Never ask for the token in chat and never put it on a
     command line (`R-safe-no-secret-cli`).
   - `token scope too small`: which scope the write needs (`repo` on GitHub, `api` on GitLab).
   - `host not confirmed` (hoster unknown or self-hosted): have the human confirm the host name, then
     enter `forge` = `github` or `gitlab` and `forge-host` = that host name (a comma list for several)
     in `docs/ai/config.md` § Git hosting. `forge.py` sends a token only to `github.com`
     (`api.github.com`), `gitlab.com`, a host named there or the host of `ACT_FORGE_API_URL`, so a
     global token never goes to a foreign host; without `forge-host` reads run without a token, and
     `whoami`, `issues --mine` and every write stop with a hint before any request. Never enter it
     unconfirmed.
   - `http only — use https`: the host is confirmed, but the remote (or `ACT_FORGE_API_URL`) is a
     plain `http://` address that is not loopback, so no token goes over it and the same calls stop.
     Switch the address to `https://`; there is no way to release a token over `http://`.
   - HTTP 401/403/404: token expired, wrong host, or no rights on the project.
