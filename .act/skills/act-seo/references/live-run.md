# Live run and public URL

Only on request. Read `R-safe-dev-server` first: the owner's dev server is theirs.

## Production build on the test port

1. **Command and port.** Build and start command: `run` in `docs/ai/config.md`, the production variant (not
   the dev server). If the build needs a database or a `.env`, ask for the start command; never read a secret
   file. Port: the one `docs/project/testing.md` names, else the server's default plus 100 (`python -m
   http.server` 8000 gives 8100, Nuxt/Next 3000 gives 3100, Vite preview 4173 gives 4273). Never a default
   port. If the test port is busy, ask; do not stop what holds it.
2. **Start** the server on that port, bound to `127.0.0.1`, in the background; wait until it answers.
   Note the process ID of the root of what you start, because step 5 ends the server by it: PowerShell
   `$p = Start-Process -PassThru -WindowStyle Hidden ...` then `$p.Id`; POSIX `setsid <command> &` (or `set -m` in a subshell) and `$!`
   (`setsid` makes the root the leader of its own process group).
3. **Crawl.** `python .act/scripts/seo_crawl.py http://127.0.0.1:<port>/` (`--no-external` to send nothing
   out; otherwise it sends one `HEAD` per external link, throttled). Exit 1 means findings, 4 a start page it
   cannot use (for example a redirect to another host). The crawl also follows `hreflang` alternates and the
   entries of the site's sitemap (read when a page links one, names a production address in its canonical link
   or carries `hreflang`), mapping the production host to the test origin; start at the site's base path. If the
   report has `sitemap-not-reached`, translated pages were not crawled: run the crawl once per language start
   page, or fix the cause named there, before judging the site as a whole. `trailing-slash-variant` (info) means
   `/de` and `/de/` return the same page on this server; most hosts redirect, so link to one form.
4. **Lighthouse.** From the crawl pick one URL per page type (home, list, detail, form, article) and run
   `python .act/scripts/seo_lighthouse.py <url> <url> ...` (three runs each, median and spread). It needs Node
   and Chrome; if they are missing, ask once before installing anything (`R-code-tools`). Without `--workdir` it
   works in `<root>/.act-local/tmp/<YYYYMMDD>-seo-lighthouse/` (today's date); when the work has a throwaway folder of its own (`.act-local/tmp/<YYYYMMDD>-<slug>/` with no task), pass it as
   `--workdir` so the files end up there. A site in several languages needs one URL per language start page
  . A failed audit lists its first entries (element, address, text);
   `--json` has all of them.
5. **Stop the server** by the process ID noted in step 2, never by name and never by searching for the port:
   `npm` and `astro` start a chain (shell, npm, node), and the process that listens is a child of it, which a
   command-line or port search easily misses (`Get-NetTCPConnection -State Listen` can list the wrong entries, `netstat` is
   localized). First check that the root is still yours: its command line must be the command you started
   (PowerShell `(Get-CimInstance Win32_Process -Filter "ProcessId=<pid>").CommandLine`; POSIX `ps -p <pid> -o args=`).
   Then end the whole tree:
   - Windows: `taskkill /T /F /PID <pid>` (from Git Bash `taskkill //T //F //PID <pid>`, else the slashes are rewritten).
   - POSIX: `kill -- -<pid>` (the process group made by `setsid`).
   Afterwards check that nothing answers on the test port any more (a request to `http://localhost:<port>/`
   must be refused (a server may listen on `::1` only)). If something still does, look at its process and command line before ending anything else.
   Stop every server you started, including a second one from a retried start. Never end a server the owner
   started, and never use `taskkill /IM`, `Stop-Process -Name` or `pkill`.

## Public URL

1. Say first, in plain words: the PageSpeed run sends the URL to Google, whose servers fetch the page. The
   crawl sends requests to the site only. Wait for a yes.
2. `python .act/scripts/seo_crawl.py --public <url>`: read-only, one request per second, 100 pages; it adds
   header checks (HSTS, compression, caching) and the real TTFB.
3. `python .act/scripts/seo_lighthouse.py --pagespeed <url>`: needs `PAGESPEED_API_KEY` in the environment.
   Without a key Google's quota is 0 and the call fails with HTTP 429; then tell the human how to get a key
   and stop. Never put the key on the command line or into a file you read.
