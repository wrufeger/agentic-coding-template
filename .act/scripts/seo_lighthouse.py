#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Lighthouse measurement for the URLs of a running site — the lab-measurement half of skill
#          `act-seo`. Runs a pinned Lighthouse version through `npx` several times per URL, takes the
#          median per category (Performance, Accessibility, Best Practices, SEO) and for LCP, CLS and TBT,
#          reports the spread next to every value, and lists the failed axe audits of the accessibility
#          category as findings. Starts no server and fixes nothing: it only takes URLs. The report keeps
#          points apart from real defects and states the target "100, or every deviation justified".
#
# What it needs: Node and `npx` on PATH, and Chrome (`CHROME_PATH`, a usual install path, or `chrome` /
#          `google-chrome` / `chromium` on PATH). If one is missing the script says so and exits 3;
#          it installs nothing. `npx --yes` downloads the pinned Lighthouse package into the npm cache
#          (assumption: npm keeps the cache where it always does; this script does not move it).
#          Limit: only Lighthouse itself is pinned, not its dependencies; two machines can differ slightly.
#          On Windows npx is started through Node and npm's `npx-cli.js`, never through cmd.exe (where
#          `&`, `|`, `^`, `%` in a URL would start other commands); if that file is not found, URLs and
#          folders containing such characters are refused (exit 2).
#
# Where files go: the Chrome profile, the Lighthouse raw data and temporary files live in a fresh
#          subfolder of one work folder, by default `<root>/.act-local/tmp/seo-lighthouse/` (option
#          `--workdir`). The child processes get it as their temp directory, the Chrome profile is passed
#          with `--user-data-dir`. The subfolder is removed afterwards (the work folder too, if this run
#          created it and it is empty); `--keep-raw` keeps the raw JSON under `raw/` with unique names.
#          A run that exceeds `--timeout` is ended with its whole process tree (by PID), then cleaned up.
#          Lighthouse's error reporting is switched off and npm's update notice is silenced.
#
# Severity (a finding's kind says whether it is a defect or only points):
#   error   defect  a failed axe audit of the accessibility category (in at least half of the runs)
#   warning defect  a failed Best Practices or SEO audit; LCP over 2500 ms, CLS over 0.1 or TBT over 200 ms
#                   (the "good" limits of Core Web Vitals / Lighthouse), measured as median
#   info    points  Performance below 100 while all three metrics are good; single performance audits
#                   below 0.9; a value whose spread is large (one run alone proves nothing)
#
# Usage:
#   python .act/scripts/seo_lighthouse.py URL [URL ...] [--runs 3] [--form-factor mobile|desktop]
#                                          [--workdir DIR] [--root DIR] [--keep-raw] [--timeout SEC] [--json]
#   python .act/scripts/seo_lighthouse.py --from-json REPORT.json [REPORT.json ...] [--json]
#   (--from-json evaluates Lighthouse JSON files that already exist, runs nothing, needs no Node or Chrome;
#    files are grouped by the URL they measured)
#
# A change in a value counts only if it is larger than that value's spread across the runs.
#
# Exit code: 0 no warning or error, 1 at least one warning or error, 2 usage problem or unreadable input,
#            3 Node, npx or Chrome missing, 4 no run produced a usable report.

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import statistics
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import urlparse

LIGHTHOUSE_VERSION = "13.6.0"
DEFAULT_RUNS = 3
DEFAULT_TIMEOUT = 240
DEFAULT_WORKDIR = Path(".act-local") / "tmp" / "seo-lighthouse"

CATEGORIES = (
    ("performance", "Performance"),
    ("accessibility", "Accessibility"),
    ("best-practices", "Best Practices"),
    ("seo", "SEO"),
)
# Metric audit id -> (label, unit, "good" limit)
METRICS = (
    ("largest-contentful-paint", "LCP", "ms", 2500.0),
    ("cumulative-layout-shift", "CLS", "", 0.1),
    ("total-blocking-time", "TBT", "ms", 200.0),
)
FAIL_BELOW = 0.9  # Lighthouse calls an audit "failed" under this score
SCORING_MODES = ("binary", "numeric", "metricSavings")
SPREAD_NOISY_SCORE = 10.0  # a category score whose range exceeds this many points is called unstable

EXIT_FINDINGS = 1
EXIT_USAGE = 2
EXIT_MISSING_TOOL = 3
EXIT_NO_DATA = 4

CHROME_CANDIDATES = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/snap/bin/chromium",
)
CHROME_NAMES = ("google-chrome", "google-chrome-stable", "chrome", "chromium", "chromium-browser")


class ToolMissing(Exception):
    """Node, npx or Chrome is not available."""


class ReportError(Exception):
    """A Lighthouse report could not be read or holds a runtime error."""


class UsageError(Exception):
    """An argument the script refuses to run with."""


class MalformedReport(ReportError):
    """The file is not shaped like a Lighthouse report (wrong types, missing parts)."""


@dataclass
class Value:
    """A measured value over several runs: median plus the range."""

    median: float
    low: float
    high: float

    @property
    def spread(self) -> float:
        return self.high - self.low


@dataclass
class AuditFailure:
    audit_id: str
    title: str
    category: str
    score: Optional[float]
    nodes: List[str] = field(default_factory=list)
    count: int = 0  # number of affected elements/items in the first run that showed it


@dataclass
class Run:
    """One Lighthouse run reduced to what the report needs."""

    scores: Dict[str, float]  # category id -> 0..100
    metrics: Dict[str, float]  # metric audit id -> raw value (ms, or unitless for CLS)
    failures: List[AuditFailure]
    form_factor: str = ""
    lighthouse_version: str = ""


@dataclass
class Finding:
    severity: str  # error | warning | info
    kind: str  # defect | points | noise
    category: str
    audit_id: str
    message: str
    nodes: List[str] = field(default_factory=list)


@dataclass
class UrlResult:
    url: str
    runs_planned: int
    runs_used: int
    run_errors: List[str]
    scores: Dict[str, Value]
    metrics: Dict[str, Value]
    findings: List[Finding]
    deviations: List[str]


def fmt(value: float) -> str:
    """Whole numbers without a decimal point, else at most two decimals."""
    if abs(value - round(value)) < 0.005:
        return str(int(round(value)))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def to_value(numbers: Sequence[float]) -> Value:
    return Value(median=float(statistics.median(numbers)), low=float(min(numbers)), high=float(max(numbers)))


# --------------------------------------------------------------------------------------------------------
# Evaluation (pure, no I/O)
# --------------------------------------------------------------------------------------------------------

def parse_report(data: object, source: str = "report") -> Run:
    """Reduce one Lighthouse JSON report to a Run.

    Raises ReportError if the run failed (runtime error) and MalformedReport if the data is not shaped like a report.
    """
    if not isinstance(data, dict):
        raise MalformedReport(f"{source}: top level is {type(data).__name__}, expected a JSON object")
    try:
        return _parse_report(data, source)
    except (TypeError, ValueError, AttributeError, KeyError) as exc:
        raise MalformedReport(f"{source}: unexpected structure ({type(exc).__name__}: {exc})")


def _parse_report(data: Mapping[str, object], source: str) -> Run:
    runtime = data.get("runtimeError")
    if isinstance(runtime, dict) and runtime.get("code") and runtime.get("code") != "NO_ERROR":
        raise ReportError(f"{source}: Lighthouse runtime error {runtime.get('code')}: {runtime.get('message', '')}")
    cats = data.get("categories")
    audits = data.get("audits")
    if not isinstance(cats, dict) or not isinstance(audits, dict):
        raise MalformedReport(f"{source}: not a Lighthouse report (no 'categories' or 'audits')")
    scores: Dict[str, float] = {}
    failures: List[AuditFailure] = []
    for cat_id, _label in CATEGORIES:
        cat = cats.get(cat_id)
        if not isinstance(cat, dict) or cat.get("score") is None:
            continue
        if isinstance(cat["score"], bool) or not isinstance(cat["score"], (int, float)):
            raise MalformedReport(f"{source}: category {cat_id} has a non-numeric score {cat['score']!r}")
        scores[cat_id] = round(float(cat["score"]) * 100, 1)
        for ref in cat.get("auditRefs", []):
            audit = audits.get(ref.get("id", ""))
            if not isinstance(audit, dict):
                continue
            score = audit.get("score")
            if score is None or audit.get("scoreDisplayMode") not in SCORING_MODES:
                continue
            if isinstance(score, bool) or not isinstance(score, (int, float)):
                raise MalformedReport(f"{source}: audit {ref.get('id')} has a non-numeric score {score!r}")
            if score >= FAIL_BELOW:
                continue
            if cat_id == "performance" and ref.get("id") in {m[0] for m in METRICS}:
                continue  # the metrics are reported on their own
            failures.append(_failure(cat_id, str(ref.get("id")), audit))
    metrics: Dict[str, float] = {}
    for metric_id, _label, _unit, _limit in METRICS:
        audit = audits.get(metric_id)
        if isinstance(audit, dict) and isinstance(audit.get("numericValue"), (int, float)):
            metrics[metric_id] = float(audit["numericValue"])
    if not scores:
        raise MalformedReport(f"{source}: report has no category with a score")
    settings = data.get("configSettings")
    form = str(settings.get("formFactor", "")) if isinstance(settings, dict) else ""
    return Run(scores=scores, metrics=metrics, failures=failures, form_factor=form,
               lighthouse_version=str(data.get("lighthouseVersion", "")))


def _failure(cat_id: str, audit_id: str, audit: Mapping[str, object]) -> AuditFailure:
    nodes: List[str] = []
    count = 0
    details = audit.get("details")
    if isinstance(details, dict):
        items = details.get("items", [])
        if isinstance(items, list):
            count = len(items)
            for item in items:
                node = item.get("node") if isinstance(item, dict) else None
                if isinstance(node, dict):
                    text = str(node.get("selector") or node.get("snippet") or "").strip()
                    if text and len(nodes) < 3:
                        nodes.append(text[:160])
    return AuditFailure(audit_id=audit_id, title=str(audit.get("title", audit_id)), category=cat_id,
                        score=audit.get("score") if isinstance(audit.get("score"), (int, float)) else None,
                        nodes=nodes, count=count)


def summarize(url: str, runs: Sequence[Run], planned: int, run_errors: Sequence[str]) -> UrlResult:
    """Median and spread per value, findings by severity, deviations from 100."""
    n = len(runs)
    scores: Dict[str, Value] = {}
    for cat_id, _label in CATEGORIES:
        series = [r.scores[cat_id] for r in runs if cat_id in r.scores]
        if series:
            scores[cat_id] = to_value(series)
    metrics: Dict[str, Value] = {}
    for metric_id, _l, _u, _limit in METRICS:
        series = [r.metrics[metric_id] for r in runs if metric_id in r.metrics]
        if series:
            metrics[metric_id] = to_value(series)

    findings: List[Finding] = []
    # Failed audits, counted over the runs; kept when they fail in at least half of them.
    seen: Dict[tuple, List[AuditFailure]] = {}
    for run in runs:
        for fail in run.failures:
            seen.setdefault((fail.category, fail.audit_id), []).append(fail)
    perf_audit_budget = 5
    for (cat_id, audit_id), hits in sorted(seen.items()):
        if len(hits) * 2 < n:
            continue
        first = max(hits, key=lambda f: len(f.nodes))
        of = f" (in {len(hits)} of {n} runs)" if len(hits) < n else ""
        if cat_id == "accessibility":
            sev, kind = "error", "defect"
        elif cat_id in ("best-practices", "seo"):
            sev, kind = "warning", "defect"
        else:
            if perf_audit_budget <= 0:
                continue
            perf_audit_budget -= 1
            sev, kind = "info", "points"
        count = f", {first.count} item(s)" if first.count else ""
        findings.append(Finding(sev, kind, cat_id, audit_id, f"{first.title}{count}{of}", list(first.nodes)))

    bad_metric = False
    for metric_id, label, unit, limit in METRICS:
        val = metrics.get(metric_id)
        if val is not None and val.median > limit:
            bad_metric = True
            findings.append(Finding("warning", "defect", "performance", metric_id,
                                    f"{label} median {fmt(val.median)}{unit and ' ' + unit} is over the good limit "
                                    f"{fmt(limit)}{unit and ' ' + unit} (spread {fmt(val.spread)})"))
    perf = scores.get("performance")
    if perf is not None and perf.median < 100 and not bad_metric:
        missing = [label for mid, label, _u, _l in METRICS if mid not in metrics]
        if missing:
            note = (f"Performance {fmt(perf.median)}: points lost; {', '.join(missing)} not measured, "
                    f"so the metrics cannot be judged")
        else:
            note = (f"Performance {fmt(perf.median)}: points lost, but LCP, CLS and TBT are within the "
                    f"good limits; no defect in the metrics")
        findings.append(Finding("info", "points", "performance", "performance-score", note))
    for cat_id, label in CATEGORIES:
        val = scores.get(cat_id)
        if val is not None and n > 1 and val.spread > SPREAD_NOISY_SCORE:
            findings.append(Finding("info", "noise", cat_id, f"{cat_id}-spread",
                                    f"{label} varies by {fmt(val.spread)} points between runs; "
                                    f"a change smaller than that is noise"))

    deviations = [f"{label} {fmt(scores[cat_id].median)}" for cat_id, label in CATEGORIES
                  if cat_id in scores and scores[cat_id].median < 100]
    order = {"error": 0, "warning": 1, "info": 2}
    findings.sort(key=lambda f: (order[f.severity], f.category, f.audit_id))
    return UrlResult(url=url, runs_planned=planned, runs_used=n, run_errors=list(run_errors), scores=scores,
                     metrics=metrics, findings=findings, deviations=deviations)


def render_text(results: Sequence[UrlResult], meta: Mapping[str, str]) -> str:
    head = " · ".join(part for part in (f"Lighthouse {meta.get('version', '?')}", meta.get("form_factor", "")) if part)
    lines: List[str] = [f"{head} · median of the runs, range in brackets"]
    for res in results:
        lines.append("")
        lines.append(f"URL {res.url}  ({res.runs_used} of {res.runs_planned} runs usable)")
        for err in res.run_errors:
            lines.append(f"  run failed: {err}")
        if not res.scores:
            lines.append("  no usable result")
            continue
        for cat_id, label in CATEGORIES:
            val = res.scores.get(cat_id)
            if val is not None:
                lines.append(f"  {label:<15} {fmt(val.median):>4}   ({fmt(val.low)}-{fmt(val.high)}, "
                             f"spread {fmt(val.spread)})")
        for metric_id, label, unit, _limit in METRICS:
            val = res.metrics.get(metric_id)
            if val is not None:
                suffix = f" {unit}" if unit else ""
                lines.append(f"  {label:<15} {fmt(val.median):>4}{suffix}   ({fmt(val.low)}-{fmt(val.high)}, "
                             f"spread {fmt(val.spread)})")
        if res.findings:
            lines.append("  Findings:")
            for f in res.findings:
                lines.append(f"    [{f.severity}/{f.kind}] {f.category} {f.audit_id}: {f.message}")
                for node in f.nodes:
                    lines.append(f"        {node}")
        else:
            lines.append("  Findings: none")
    lines.append("")
    deviating = [r for r in results if r.deviations]
    if deviating:
        lines.append("Target: 100, or every deviation justified. Deviations: "
                     + "; ".join(f"{r.url}: {', '.join(r.deviations)}" for r in deviating) + ".")
    else:
        lines.append("Target 100 reached in all categories on the measured URLs.")
    lines.append("Points are not defects: a Performance score below 100 with good metrics, or an axe-clean "
                 "Accessibility 100 (axe covers roughly a third of WCAG; the rest is a manual check), is not "
                 "a reason to trade content or accessibility for points. This report fixes nothing; changes "
                 "need the owner's go-ahead. A change counts only if it exceeds the spread shown.")
    return "\n".join(lines)


def exit_code(results: Sequence[UrlResult]) -> int:
    if all(not r.scores for r in results):
        return EXIT_NO_DATA
    for res in results:
        if any(f.severity in ("error", "warning") for f in res.findings):
            return EXIT_FINDINGS
    return 0


# --------------------------------------------------------------------------------------------------------
# Tools and runs
# --------------------------------------------------------------------------------------------------------

def find_chrome(env: Mapping[str, str], candidates: Optional[Sequence[str]] = None,
                which: Callable[[str], Optional[str]] = shutil.which) -> Optional[str]:
    """Path of a Chrome binary, or None. A CHROME_PATH that points nowhere raises ToolMissing."""
    configured = env.get("CHROME_PATH")
    if configured:
        if Path(configured).is_file():
            return configured
        raise ToolMissing(f"CHROME_PATH is set to {configured}, but no file exists there")
    local = env.get("LOCALAPPDATA")
    extra = [str(Path(local) / "Google" / "Chrome" / "Application" / "chrome.exe")] if local else []
    for cand in (list(CHROME_CANDIDATES) + extra if candidates is None else candidates):
        if Path(cand).is_file():
            return cand
    for name in CHROME_NAMES:
        found = which(name)
        if found:
            return found
    return None


CMD_METACHARS = '&|<>^%!"'


def cmd_unsafe(text: str) -> Optional[str]:
    """The first character in `text` that cmd.exe would interpret, or None."""
    for ch in text:
        if ch in CMD_METACHARS:
            return ch
    return None


def find_npx_cli(node: str, npx: str) -> Optional[str]:
    """npm's own npx-cli.js next to node or npx (Windows layout), so Node can start it without cmd.exe."""
    for base in (Path(node).resolve().parent, Path(npx).resolve().parent):
        cli = base / "node_modules" / "npm" / "bin" / "npx-cli.js"
        if cli.is_file():
            return str(cli)
    return None


def build_runner(node: str, npx: str, windows: bool) -> List[str]:
    """Command prefix that starts npx. On Windows `npx` is a .cmd file that runs through cmd.exe, where
    & | ^ % in an argument start other commands; so Node runs npm's npx-cli.js directly. Returns the plain
    npx when there is no such file; the caller then refuses arguments with cmd metacharacters."""
    if windows:
        cli = find_npx_cli(node, npx)
        if cli:
            return [node, cli]
    return [npx]


def runner_goes_through_cmd(runner: Sequence[str], windows: bool) -> bool:
    return windows and Path(runner[0]).suffix.lower() in (".cmd", ".bat")


def check_tools(env: Mapping[str, str]) -> Dict[str, object]:
    """Locate node, npx and Chrome; raises ToolMissing with a message saying what to install."""
    path = env.get("PATH")
    node = shutil.which("node", path=path)
    if not node:
        raise ToolMissing("Node.js was not found on PATH. Lighthouse needs Node (an LTS version); "
                          "install it yourself, this script installs nothing.")
    npx = shutil.which("npx", path=path)
    if not npx:
        raise ToolMissing("npx was not found on PATH (it ships with npm, next to Node). "
                          "Install npm yourself, this script installs nothing.")
    chrome = find_chrome(env)
    if not chrome:
        raise ToolMissing("Chrome was not found (CHROME_PATH, the usual install paths, chrome/google-chrome/"
                          "chromium on PATH). Lighthouse needs it; install it yourself or set CHROME_PATH, "
                          "this script installs nothing.")
    return {"node": node, "npx": npx, "chrome": chrome, "runner": build_runner(node, npx, os.name == "nt")}


def lighthouse_command(runner: Sequence[str], url: str, out_json: Path, profile: Path,
                       form_factor: str) -> List[str]:
    flags = f'--headless=new --user-data-dir="{profile}" --no-first-run --disable-extensions'
    cmd = list(runner) + ["--yes", f"lighthouse@{LIGHTHOUSE_VERSION}", url, "--output=json",
                          f"--output-path={out_json}", "--quiet", "--no-enable-error-reporting",
                          f"--chrome-flags={flags}", "--only-categories=performance,accessibility,best-practices,seo"]
    if form_factor == "desktop":
        cmd.append("--preset=desktop")
    return cmd


def remove_tree(path: Path) -> None:
    """rmtree with a few retries: on Windows Chrome may hold a lock for a moment after it exits."""
    for attempt in range(5):
        try:
            shutil.rmtree(path)
            return
        except FileNotFoundError:
            return
        except OSError:
            time.sleep(0.5 * (attempt + 1))
    shutil.rmtree(path, ignore_errors=True)


def kill_tree(proc: "subprocess.Popen[bytes]") -> None:
    """End the process and everything it started. By PID only, never by name."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, timeout=30)
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    try:
        proc.kill()
    except OSError:
        pass


def run_logged(cmd: Sequence[str], log: Path, timeout: int, env: Mapping[str, str],
               cwd: Path) -> Tuple[Optional[int], str]:
    """Run `cmd` in its own process group with output in a file. Returns (exit code, log tail); the exit
    code is None after a timeout, when the whole process tree has been ended."""
    kwargs: Dict[str, object] = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    with log.open("wb") as sink:
        proc = subprocess.Popen(list(cmd), stdout=sink, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                env=dict(env), cwd=str(cwd), **kwargs)  # type: ignore[call-overload]
        code: Optional[int]
        try:
            code = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            kill_tree(proc)
            proc.wait()
            code = None
    tail = " ".join(log.read_text(encoding="utf-8", errors="replace").split())[-300:]
    return code, tail


def measure(urls: Sequence[str], runs: int, workdir: Path, keep_raw: bool, timeout: int,
            form_factor: str, env: Mapping[str, str]) -> List[UrlResult]:
    tools = check_tools(env)
    runner = list(tools["runner"])  # type: ignore[call-overload]
    if runner_goes_through_cmd(runner, os.name == "nt"):
        for label, text in [("URL", u) for u in urls] + [("work folder", str(workdir))]:
            bad = cmd_unsafe(text)
            if bad:
                raise UsageError(f"{label} {text!r} contains {bad!r}, which cmd.exe would interpret, and npm's "
                                 f"npx-cli.js was not found to start npx without cmd.exe; refusing to run it")
    created = not workdir.exists()
    workdir.mkdir(parents=True, exist_ok=True)
    session = Path(tempfile.mkdtemp(prefix="run-", dir=str(workdir)))
    temp = session / "temp"
    temp.mkdir()
    child_env = dict(env)
    child_env.update({"CHROME_PATH": str(tools["chrome"]), "TEMP": str(temp), "TMP": str(temp),
                      "TMPDIR": str(temp), "NPM_CONFIG_UPDATE_NOTIFIER": "false"})
    results: List[UrlResult] = []
    try:
        for u_index, url in enumerate(urls):
            good: List[Run] = []
            errors: List[str] = []
            for r_index in range(runs):
                profile = session / f"profile-{u_index}-{r_index}"
                out_json = session / f"lh-{u_index}-{r_index}.json"
                log = session / f"log-{u_index}-{r_index}.txt"
                cmd = lighthouse_command(runner, url, out_json, profile, form_factor)
                try:
                    code, tail = run_logged(cmd, log, timeout, child_env, session)
                except OSError as exc:
                    errors.append(f"run {r_index + 1}: could not start npx ({exc})")
                    continue
                finally:
                    if profile.exists():
                        remove_tree(profile)
                if code is None:
                    errors.append(f"run {r_index + 1}: no result after {timeout} s (process tree ended)")
                    continue
                if not out_json.is_file():
                    errors.append(f"run {r_index + 1}: exit {code}, no report; {tail}")
                    continue
                try:
                    good.append(parse_report(json.loads(out_json.read_text(encoding="utf-8")),
                                             f"run {r_index + 1}"))
                except (ValueError, ReportError) as exc:
                    errors.append(str(exc))
            results.append(summarize(url, good, runs, errors) if good
                           else UrlResult(url, runs, 0, errors, {}, {}, [], []))
        if keep_raw:
            kept = workdir / "raw"
            kept.mkdir(exist_ok=True)
            for src in session.glob("lh-*.json"):
                shutil.copy2(src, kept / f"{session.name}-{src.name}")  # unique per run, never overwrites
    finally:
        remove_tree(session)
        if created:
            try:
                workdir.rmdir()  # only a folder this run made, and only if it is empty
            except OSError:
                pass
    return results


def load_reports(files: Sequence[str]) -> List[UrlResult]:
    """Evaluate existing Lighthouse JSON files, grouped by the URL they measured.
    Unreadable or wrongly shaped files raise ReportError (naming the file); a report of a failed run
    (runtime error) counts as a failed run."""
    groups: Dict[str, List[Run]] = {}
    errors: Dict[str, List[str]] = {}
    for name in files:
        path = Path(name)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ReportError(f"{name}: cannot read as JSON ({exc})")
        if not isinstance(data, dict):
            raise MalformedReport(f"{name}: top level is {type(data).__name__}, expected a JSON object")
        url = str(data.get("finalDisplayedUrl") or data.get("finalUrl") or data.get("requestedUrl") or name)
        try:
            groups.setdefault(url, []).append(parse_report(data, name))
        except MalformedReport:
            raise
        except ReportError as exc:
            groups.setdefault(url, [])
            errors.setdefault(url, []).append(str(exc))
    return [summarize(url, runs, len(runs) + len(errors.get(url, [])), errors.get(url, []))
            if runs else UrlResult(url, len(errors.get(url, [])), 0, errors.get(url, []), {}, {}, [], [])
            for url, runs in groups.items()]


# --------------------------------------------------------------------------------------------------------
# Command line
# --------------------------------------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Lighthouse median over several runs per URL, spread per value, axe findings, report by "
                    "severity. Takes URLs of an already running site; starts no server and fixes nothing.")
    p.add_argument("urls", nargs="*", help="http(s) URLs to measure")
    p.add_argument("--runs", type=int, default=DEFAULT_RUNS, help=f"runs per URL (default {DEFAULT_RUNS})")
    p.add_argument("--form-factor", choices=("mobile", "desktop"), default="mobile",
                   help="Lighthouse emulation (default mobile)")
    p.add_argument("--workdir", help="folder for Chrome profile, raw data and temp files "
                                     "(default <root>/.act-local/tmp/seo-lighthouse)")
    p.add_argument("--root", default=".", help="project root for the default workdir (default: current directory)")
    p.add_argument("--keep-raw", action="store_true", help="keep the raw Lighthouse JSON under <workdir>/raw")
    p.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="seconds per run (default %(default)s)")
    p.add_argument("--from-json", nargs="+", metavar="FILE",
                   help="evaluate existing Lighthouse JSON files instead of measuring")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    meta = {"version": LIGHTHOUSE_VERSION, "form_factor": args.form_factor}
    if args.from_json:
        if args.urls:
            print("seo_lighthouse: give URLs or --from-json, not both", file=sys.stderr)
            return EXIT_USAGE
        try:
            results = load_reports(args.from_json)
        except ReportError as exc:
            print(f"seo_lighthouse: {exc}", file=sys.stderr)
            return EXIT_USAGE
        meta = {"version": "(existing reports)", "form_factor": ""}
    else:
        if not args.urls:
            print("seo_lighthouse: give at least one URL (or --from-json)", file=sys.stderr)
            return EXIT_USAGE
        if args.runs < 1:
            print(f"seo_lighthouse: --runs must be at least 1, got {args.runs}", file=sys.stderr)
            return EXIT_USAGE
        for url in args.urls:
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                print(f"seo_lighthouse: not an http(s) URL: {url}", file=sys.stderr)
                return EXIT_USAGE
        if not args.workdir and not Path(args.root).is_dir():
            print(f"seo_lighthouse: --root {args.root} is not an existing folder", file=sys.stderr)
            return EXIT_USAGE
        workdir = Path(args.workdir) if args.workdir else Path(args.root) / DEFAULT_WORKDIR
        try:
            results = measure(args.urls, args.runs, workdir.resolve(), args.keep_raw, args.timeout,
                              args.form_factor, os.environ)
        except ToolMissing as exc:
            print(f"seo_lighthouse: {exc}", file=sys.stderr)
            return EXIT_MISSING_TOOL
        except UsageError as exc:
            print(f"seo_lighthouse: {exc}", file=sys.stderr)
            return EXIT_USAGE
    if args.json:
        payload = {"lighthouse_version": LIGHTHOUSE_VERSION, "target": "100, or every deviation justified",
                   "results": [asdict(r) for r in results]}
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(render_text(results, meta))
    return exit_code(results)


if __name__ == "__main__":
    sys.exit(main())
