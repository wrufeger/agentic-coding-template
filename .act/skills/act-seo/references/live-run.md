# Live run and public URL

Only on request. Read `R-safe-dev-server` first: the owner's dev server is theirs.

## Production build on the test port

1. **Command and port.** Build and start command: `run` in `docs/ai/config.md`, the production variant (not
   the dev server). If the build needs a database or a `.env`, ask for the start command; never read a secret
   file. Port: the one `docs/project/testing.md` names, else the server's default plus 100 (`python -m
   http.server` 8000 gives 8100, Nuxt/Next 3000 gives 3100, Vite preview 4173 gives 4273). Never a default
   port. If the test port is busy, ask; do not stop what holds it.
2. **Start** the server on that port, bound to `127.0.0.1`, in the background; wait until it answers.
3. **Crawl.** `python .act/scripts/seo_crawl.py http://127.0.0.1:<port>/` (`--no-external` to send nothing
   out; otherwise it sends one `HEAD` per external link, throttled). Exit 1 means findings, 4 a start page it
   cannot use (for example a redirect to another host).
4. **Lighthouse.** From the crawl pick one URL per page type (home, list, detail, form, article) and run
   `python .act/scripts/seo_lighthouse.py <url> <url> ...` (three runs each, median and spread). It needs Node
   and Chrome; if they are missing, ask once before installing anything (`R-code-tools`).
5. **Stop the server** by PID, never by name. Find the PID, then check that its listening port is the test
   port and its command line is the command you started, and only then end it.
   - POSIX: `lsof -ti tcp:<port> -sTCP:LISTEN`, then `ps -p <pid> -o args=`, then `kill <pid>`.
   - Windows: `Get-NetTCPConnection` can miss the listener of `python -m http.server`; use
     `Get-CimInstance Win32_Process | Where-Object CommandLine -like '*<port>*' | Select ProcessId, CommandLine`,
     check the command line, then `Stop-Process -Id <pid>`. Do not match on `findstr ":<port> "`.
   - Stop every server you started, including a second one from a retried start.

## Public URL

1. Say first, in plain words: the PageSpeed run sends the URL to Google, whose servers fetch the page. The
   crawl sends requests to the site only. Wait for a yes.
2. `python .act/scripts/seo_crawl.py --public <url>`: read-only, one request per second, 100 pages; it adds
   header checks (HSTS, compression, caching) and the real TTFB.
3. `python .act/scripts/seo_lighthouse.py --pagespeed <url>`: needs `PAGESPEED_API_KEY` in the environment.
   Without a key Google's quota is 0 and the call fails with HTTP 429; then tell the human how to get a key
   and stop. Never put the key on the command line or into a file you read.
