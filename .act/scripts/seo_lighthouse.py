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
#          subfolder of one work folder, by default `<root>/.act-local/tmp/<YYYYMMDD>-seo-lighthouse/` (option
#          `--workdir`). The child processes get it as their temp directory, the Chrome profile is passed
#          with `--user-data-dir`. The subfolder is removed afterwards (the work folder too, if this run
#          created it and it is empty); `--keep-raw` keeps the raw JSON under `raw/` with unique names.
#          A run that exceeds `--timeout` is ended with its whole process tree (by PID), then cleaned up.
#          Lighthouse's error reporting is switched off and npm's update notice is silenced.
#
# Where it failed: a failed audit lists its first three entries (selector or snippet, address, text; each
#          shortened to 200 characters) under the finding; `--json` carries all entries (`entries`, up to 200).
#
# Severity (a finding's kind says whether it is a defect or only points):
#   error   defect  a failed axe audit of the accessibility category (in at least half of the runs)
#   warning defect  a failed Best Practices or SEO audit; LCP over 2500 ms, CLS over 0.1 or TBT over 200 ms
#                   (the "good" limits of Core Web Vitals / Lighthouse), measured as median
#   info    points  Performance below 100 while all three metrics are good; single performance audits
#                   below 0.9; a value whose spread is large (one run alone proves nothing)
#
# PageSpeed Insights (--pagespeed): for a public URL, Google runs Lighthouse and returns the result in the same
#          format; the evaluation above is reused unchanged. Needs no Node and no Chrome. The URL is SENT TO
#          GOOGLE (the request goes to googleapis.com and Google's servers fetch the page); nothing else leaves
#          the machine. Field data (CrUX: real visitors, `loadingExperience`) is added when Google has it for the
#          page or its origin; a field value rated SLOW is a warning, AVERAGE is info. Only public URLs work:
#          localhost and private addresses are refused. One run per URL by default (--runs), one second between
#          calls. An API key is optional in the code, but Google's quota without a key is 0 per day at the time
#          of writing, so a key is needed in practice: put it in the environment variable PAGESPEED_API_KEY
#          (create it in a Google Cloud project with the PageSpeed Insights API enabled). It is never accepted as
#          an argument and never printed. 429 (quota used up or none without a key) and 400/403 on the key are
#          reported with what to do. PAGESPEED_ENDPOINT (environment only) replaces the endpoint for tests; the
#          key is sent only to the real endpoint or to a loopback address.
#
# Usage:
#   python .act/scripts/seo_lighthouse.py URL [URL ...] [--runs 3] [--form-factor mobile|desktop]
#                                          [--workdir DIR] [--root DIR] [--keep-raw] [--timeout SEC] [--json]
#   python .act/scripts/seo_lighthouse.py --pagespeed URL [URL ...] [--runs 1] [--form-factor mobile|desktop]
#                                          [--timeout SEC] [--json]       (the URL goes to Google)
#   python .act/scripts/seo_lighthouse.py --from-json REPORT.json [REPORT.json ...] [--json]
#   (--from-json evaluates Lighthouse JSON files that already exist, runs nothing, needs no Node or Chrome;
#    files are grouped by the URL they measured)
#
# A change in a value counts only if it is larger than that value's spread across the runs.
#
# Exit code: 0 no warning or error, 1 at least one warning or error, 2 usage problem or unreadable input,
#            3 Node, npx or Chrome missing, 4 no run produced a usable report (with --pagespeed also: quota used up).

from __future__ import annotations

import argparse
import datetime
import http.client
import ipaddress
import json
import os
import shutil
import re
import signal
import socket
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import urlencode, urlparse

LIGHTHOUSE_VERSION = "13.6.0"
DEFAULT_RUNS = 3
DEFAULT_TIMEOUT = 240


def default_workdir() -> Path:
    """The work folder of a run with no task: `.act-local/tmp/<YYYYMMDD>-seo-lighthouse` (today's date)."""
    return Path(".act-local") / "tmp" / f"{datetime.date.today():%Y%m%d}-seo-lighthouse"


PSI_ENDPOINT = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
PSI_KEY_ENV = "PAGESPEED_API_KEY"
PSI_ENDPOINT_ENV = "PAGESPEED_ENDPOINT"
PSI_DELAY = 1.0  # seconds between two calls
PSI_DEFAULT_RUNS = 1
PSI_MAX_BYTES = 30_000_000
# CrUX metric in the API -> (label, unit, factor to the shown value; CLS comes as hundredths)
FIELD_METRICS = (
    ("LARGEST_CONTENTFUL_PAINT_MS", "LCP", "ms", 1.0),
    ("CUMULATIVE_LAYOUT_SHIFT_SCORE", "CLS", "", 0.01),
    ("INTERACTION_TO_NEXT_PAINT", "INP", "ms", 1.0),
    ("FIRST_CONTENTFUL_PAINT_MS", "FCP", "ms", 1.0),
    ("EXPERIMENTAL_TIME_TO_FIRST_BYTE", "TTFB", "ms", 1.0),
)
FIELD_JUDGED = ("LCP", "CLS", "INP")  # the Core Web Vitals; their SLOW / AVERAGE rating becomes a finding

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
SHOWN_ENTRIES = 3  # entries of a failed audit shown in the text report, each shortened to SHOWN_ENTRY_CHARS
SHOWN_ENTRY_CHARS = 200
MAX_ENTRIES = 200  # entries of one audit kept for the JSON
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


class PagespeedError(Exception):
    """A PageSpeed Insights call failed. `stop` means further calls would fail the same way (quota, key)."""

    def __init__(self, message: str, stop: bool = False) -> None:
        super().__init__(message)
        self.stop = stop


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
    nodes: List[str] = field(default_factory=list)  # the first entries, shortened
    count: int = 0  # number of affected elements/items in the first run that showed it
    entries: List[str] = field(default_factory=list)  # all entries (capped), not shortened


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
    nodes: List[str] = field(default_factory=list)  # where it is: the first entries, shortened (text report)
    entries: List[str] = field(default_factory=list)  # all entries of the audit, not shortened (JSON)


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
    field_data: Dict[str, object] = field(default_factory=dict)  # CrUX field data (PageSpeed Insights only)
    source: str = "local"  # local | pagespeed


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
    entries: List[str] = []
    count = 0
    details = audit.get("details")
    if isinstance(details, dict):
        items = details.get("items", [])
        if isinstance(items, list):
            count = len(items)
            for item in items[:MAX_ENTRIES]:
                text = describe_item(item)
                if text:
                    entries.append(text)
    return AuditFailure(audit_id=audit_id, title=str(audit.get("title", audit_id)), category=cat_id,
                        score=audit.get("score") if isinstance(audit.get("score"), (int, float)) else None,
                        nodes=[e[:SHOWN_ENTRY_CHARS] for e in entries[:SHOWN_ENTRIES]], count=count,
                        entries=entries)


def _scalar(value: object) -> str:
    """Text of an item field: a string as it is, a typed value (`{"type": "link", "url": ...}`) by its url,
    value or text, anything else empty."""
    if isinstance(value, str):
        return " ".join(value.split())
    if isinstance(value, dict):
        for key in ("url", "value", "text", "selector", "snippet"):
            if isinstance(value.get(key), str) and value[key].strip():
                return " ".join(value[key].split())
    return ""


def describe_item(item: object) -> str:
    """Where an audit failed: the element (selector, else snippet), then address and text of the item. An item
    that is only an element gives just the selector. Pure."""
    if not isinstance(item, dict):
        return ""
    parts: List[str] = []
    node = item.get("node")
    label = ""
    if isinstance(node, dict):
        parts.append(_scalar(node.get("selector")) or _scalar(node.get("snippet")))
        label = _scalar(node.get("nodeLabel"))
    for key in ("url", "href", "source"):
        parts.append(_scalar(item.get(key)))
    for key in ("text", "label", "name"):
        parts.append(_scalar(item.get(key)))
    if label:
        parts.append(f'"{label}"' if label not in parts else "")
    seen: List[str] = []
    for part in parts:
        if part and part not in seen:
            seen.append(part)
    return "  |  ".join(seen)


def parse_field_data(payload: object) -> Dict[str, object]:
    """Field data (CrUX) of a PageSpeed Insights answer: the page's own `loadingExperience` if it has metrics,
    else the origin's. Empty when Google has none (too little traffic). Pure."""
    if not isinstance(payload, dict):
        return {}
    for key, scope in (("loadingExperience", "page"), ("originLoadingExperience", "origin")):
        exp = payload.get(key)
        metrics = exp.get("metrics") if isinstance(exp, dict) else None
        if not isinstance(metrics, dict):
            continue
        out: Dict[str, object] = {}
        for api_name, label, unit, factor in FIELD_METRICS:
            m = metrics.get(api_name)
            percentile = m.get("percentile") if isinstance(m, dict) else None
            if isinstance(percentile, (int, float)) and not isinstance(percentile, bool):
                out[label] = {"p75": round(float(percentile) * factor, 3), "unit": unit,
                              "category": str(m.get("category", ""))}
        if out:
            return {"scope": scope, "overall": str(exp.get("overall_category", "")), "metrics": out}
    return {}


def summarize(url: str, runs: Sequence[Run], planned: int, run_errors: Sequence[str],
              field_data: Optional[Mapping[str, object]] = None) -> UrlResult:
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
        first = max(hits, key=lambda f: (len(f.nodes), len(f.entries)))
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
        findings.append(Finding(sev, kind, cat_id, audit_id, f"{first.title}{count}{of}", list(first.nodes),
                                list(first.entries)))

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

    field_metrics = (field_data or {}).get("metrics")
    if isinstance(field_metrics, dict):
        scope = str(field_data.get("scope", ""))  # type: ignore[union-attr]
        for label in FIELD_JUDGED:
            entry = field_metrics.get(label)
            rating = entry.get("category") if isinstance(entry, dict) else None
            if rating in ("SLOW", "AVERAGE"):
                unit = f" {entry['unit']}" if entry.get("unit") else ""
                findings.append(Finding("warning" if rating == "SLOW" else "info",
                                        "defect" if rating == "SLOW" else "points", "performance",
                                        f"field-{label.lower()}",
                                        f"real visitors ({scope} data): {label} p75 {fmt(entry['p75'])}{unit} "
                                        f"is rated {rating}"))
    deviations = [f"{label} {fmt(scores[cat_id].median)}" for cat_id, label in CATEGORIES
                  if cat_id in scores and scores[cat_id].median < 100]
    order = {"error": 0, "warning": 1, "info": 2}
    findings.sort(key=lambda f: (order[f.severity], f.category, f.audit_id))
    return UrlResult(url=url, runs_planned=planned, runs_used=n, run_errors=list(run_errors), scores=scores,
                     metrics=metrics, findings=findings, deviations=deviations,
                     field_data=dict(field_data or {}), source="pagespeed" if field_data is not None else "local")


def render_field_data(data: Mapping[str, object]) -> List[str]:
    metrics = data.get("metrics")
    if not isinstance(metrics, dict) or not metrics:
        return ["  Field data (real visitors, CrUX): none; Google has too little traffic data for this page "
                "or its origin, so only the lab values above exist"]
    scope = "this page" if data.get("scope") == "page" else "the whole origin (not enough data for the page)"
    out = [f"  Field data (real visitors, CrUX, 75th percentile, {scope}):"]
    for label, entry in metrics.items():
        if isinstance(entry, dict):
            unit = f" {entry['unit']}" if entry.get("unit") else ""
            out.append(f"    {label:<15} {fmt(entry['p75']):>6}{unit}   {entry.get('category', '')}")
    return out


def render_text(results: Sequence[UrlResult], meta: Mapping[str, str]) -> str:
    head = " · ".join(part for part in (f"Lighthouse {meta.get('version', '?')}", meta.get("form_factor", "")) if part)
    lines: List[str] = [f"{head} · median of the runs, range in brackets"]
    if meta.get("source") == "pagespeed" and meta.get("endpoint_host"):
        lines.append(f"Measured through the endpoint {meta['endpoint_host']} (PAGESPEED_ENDPOINT override), "
                     "not through Google; the URL(s) below were sent there.")
    elif meta.get("source") == "pagespeed":
        lines.append("Measured by Google PageSpeed Insights: the URL(s) below were sent to Google, whose servers "
                     "fetched the page. Lab values come from Google's machines, not from this one.")
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
        if res.source == "pagespeed":
            lines += render_field_data(res.field_data)
        if res.findings:
            lines.append("  Findings:")
            for f in res.findings:
                lines.append(f"    [{f.severity}/{f.kind}] {f.category} {f.audit_id}: {f.message}")
                for node in f.nodes:
                    lines.append(f"        {node}")
                if len(f.entries) > len(f.nodes):
                    lines.append(f"        ... {len(f.entries) - len(f.nodes)} more (use --json)")
        else:
            lines.append("  Findings: none")
    lines.append("")
    deviating = [r for r in results if r.deviations]
    if deviating:
        lines.append("Target: 100, or every deviation justified. Deviations: "
                     + "; ".join(f"{r.url}: {', '.join(r.deviations)}" for r in deviating) + ".")
    elif not any(r.scores for r in results):
        lines.append("No URL gave a usable result, so nothing can be said about the target.")
        return "\n".join(lines)
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


LOCAL_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home.arpa", ".localdomain", ".intranet",
                  ".corp", ".home", ".arpa")


def resolve_host(host: str) -> List[str]:
    """Addresses a name resolves to (empty when it does not resolve). Replaceable in tests."""
    try:
        return sorted({str(info[4][0]).split("%")[0] for info in socket.getaddrinfo(host, None)})
    except (OSError, UnicodeError):
        return []


def _global(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    mapped = getattr(ip, "ipv4_mapped", None)
    ip = mapped or ip
    return bool(ip.is_global and not ip.is_multicast)


def is_public_host(host: str, resolver: Callable[[str], List[str]] = resolve_host) -> bool:
    """True only if Google can reach the host from the internet: every address it stands for is global.
    Rejected: empty and single-label names, local suffixes (.local, .internal, .home.arpa ...), address literals
    that are not global (including the short forms inet_aton reads, such as 127.1 or 2130706433), and names
    that do not resolve or resolve to any non-global address (10.x, 100.64.x, loopback, multicast ...)."""
    host = host.strip().lower().rstrip(".")
    if not host or "%" in host or host == "localhost" or "." not in host and ":" not in host and not host.isdigit():
        return False
    if host.endswith(LOCAL_SUFFIXES):
        return False
    try:
        return _global(host)
    except ValueError:
        pass
    if host[0].isdigit() and re.fullmatch(r"[0-9a-fx.]+", host):
        try:
            return _global(socket.inet_ntoa(socket.inet_aton(host)))
        except (OSError, ValueError):
            pass
    addresses = resolver(host)
    if not addresses:
        return False
    try:
        return all(_global(a) for a in addresses)
    except ValueError:
        return False


def key_may_go_to(endpoint: str) -> bool:
    """The API key is sent only to the real endpoint or to a loopback address (tests)."""
    parts = urlparse(endpoint)
    host = (parts.hostname or "").lower()
    if endpoint == PSI_ENDPOINT:
        return True
    try:
        return host == "localhost" or ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def scrub(text: str, key: str) -> str:
    return text.replace(key, "***") if key else text


def request_pagespeed(url: str, strategy: str, key: str, timeout: float, endpoint: str = PSI_ENDPOINT) -> dict:
    """One PageSpeed Insights call; returns the parsed JSON answer. Raises PagespeedError with a message that
    never holds the key."""
    query = [("url", url), ("strategy", strategy)] + [("category", c) for c, _label in CATEGORIES]
    if key and key_may_go_to(endpoint):
        query.append(("key", key))
    try:
        request = urllib.request.Request(f"{endpoint}?{urlencode(query)}",
                                         headers={"User-Agent": "act-seo-lighthouse/1.0", "Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(PSI_MAX_BYTES + 1)
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read(65536).decode("utf-8", errors="replace")
        except OSError:
            pass
        message = ""
        try:
            message = str(json.loads(body).get("error", {}).get("message", ""))
        except (ValueError, AttributeError):
            pass
        message = scrub(" ".join(message.split())[:300], key)
        if exc.code == 429:
            if key:
                raise PagespeedError(f"PageSpeed Insights quota exceeded (HTTP 429) for your API key "
                                     f"({PSI_KEY_ENV}); wait for the quota to reset or raise it in the Google "
                                     f"Cloud console. Google said: {message}", stop=True)
            raise PagespeedError(f"PageSpeed Insights quota exceeded (HTTP 429) and no API key is set. Without "
                                 f"a key Google's quota is 0 per day; create a key (Google Cloud project, "
                                 f"PageSpeed Insights API enabled) and put it in the environment variable "
                                 f"{PSI_KEY_ENV}, never on the command line. Google said: {message}", stop=True)
        if exc.code in (400, 403) and "key" in (message + body[:400]).lower():
            raise PagespeedError(f"PageSpeed Insights refused the API key in {PSI_KEY_ENV} (HTTP {exc.code}): "
                                 f"check that the key is valid and the PageSpeed Insights API is enabled for it. "
                                 f"Google said: {message}", stop=True)
        raise PagespeedError(f"PageSpeed Insights answered HTTP {exc.code}: {message or 'no message'}",
                             stop=exc.code in (401, 403))
    except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError) as exc:
        raise PagespeedError(f"no answer from PageSpeed Insights ({scrub(type(exc).__name__ + ': ' + str(exc), key)})")
    if len(raw) > PSI_MAX_BYTES:
        raise PagespeedError(f"the PageSpeed Insights answer is larger than {PSI_MAX_BYTES} bytes; not read")
    try:
        data = json.loads(raw.decode("utf-8", errors="replace"))
    except ValueError as exc:
        raise PagespeedError(f"the PageSpeed Insights answer is not JSON ({exc})")
    if not isinstance(data, dict) or not isinstance(data.get("lighthouseResult"), dict):
        raise PagespeedError("the PageSpeed Insights answer has no lighthouseResult")
    return data


def measure_pagespeed(urls: Sequence[str], runs: int, form_factor: str, env: Mapping[str, str],
                      timeout: float, sleep: Callable[[float], None] = time.sleep,
                      requester: Optional[Callable[..., dict]] = None) -> Tuple[List[UrlResult], str]:
    """Measure each URL `runs` times through PageSpeed Insights. After a quota or key error no further call
    is made (it would fail the same way); the remaining URLs get that error. Returns (results, Lighthouse version)."""
    key = env.get(PSI_KEY_ENV, "").strip()
    endpoint = env.get(PSI_ENDPOINT_ENV, "").strip() or PSI_ENDPOINT
    call = requester or request_pagespeed
    results: List[UrlResult] = []
    version = ""
    stopped = ""
    first_call = True
    for url in urls:
        good: List[Run] = []
        errors: List[str] = []
        field_data: Dict[str, object] = {}
        for r_index in range(runs):
            if stopped:
                errors.append(f"run {r_index + 1}: not tried ({stopped})")
                continue
            if not first_call:
                sleep(PSI_DELAY)
            first_call = False
            try:
                data = call(url, form_factor, key, timeout, endpoint)
                run = parse_report(data["lighthouseResult"], f"run {r_index + 1}")
            except PagespeedError as exc:
                errors.append(f"run {r_index + 1}: {exc}")
                if exc.stop:
                    stopped = str(exc)
                continue
            except ReportError as exc:
                errors.append(str(exc))
                continue
            good.append(run)
            version = version or run.lighthouse_version
            field_data = field_data or parse_field_data(data)
        results.append(summarize(url, good, runs, errors, field_data) if good
                       else UrlResult(url, runs, 0, errors, {}, {}, [], [], source="pagespeed"))
    return results, version


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
    p.add_argument("--runs", type=int, default=None,
                   help=f"runs per URL (default {DEFAULT_RUNS}, with --pagespeed {PSI_DEFAULT_RUNS})")
    p.add_argument("--form-factor", choices=("mobile", "desktop"), default="mobile",
                   help="Lighthouse emulation (default mobile)")
    p.add_argument("--workdir", help="folder for Chrome profile, raw data and temp files "
                                     "(default <root>/.act-local/tmp/<YYYYMMDD>-seo-lighthouse)")
    p.add_argument("--root", default=".", help="project root for the default workdir (default: current directory)")
    p.add_argument("--keep-raw", action="store_true", help="keep the raw Lighthouse JSON under <workdir>/raw")
    p.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="seconds per run (default %(default)s)")
    p.add_argument("--from-json", nargs="+", metavar="FILE",
                   help="evaluate existing Lighthouse JSON files instead of measuring")
    p.add_argument("--pagespeed", action="store_true",
                   help="measure a PUBLIC url with Google PageSpeed Insights instead of local Chrome: THE URL IS "
                        "SENT TO GOOGLE, whose servers fetch the page. Same evaluation, plus field data (CrUX) when "
                        f"Google has it. The API key is read from the environment variable {PSI_KEY_ENV} only, "
                        "never from an argument; Google's quota without a key is 0 per day, so a key is needed. "
                        "No Node or Chrome needed")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run; any unexpected exception ends as one line with the key removed, never as a traceback (a request
    URL inside an exception text carries the API key)."""
    try:
        return run_cli(argv)
    except Exception as exc:  # noqa: BLE001 - last line of defence, the message is filtered
        key = os.environ.get(PSI_KEY_ENV, "").strip()
        print(f"seo_lighthouse: unexpected error ({type(exc).__name__}: {scrub(str(exc), key)})", file=sys.stderr)
        return EXIT_NO_DATA


def run_cli(argv: Optional[Sequence[str]] = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    meta = {"version": LIGHTHOUSE_VERSION, "form_factor": args.form_factor}
    if args.pagespeed and (args.from_json or args.keep_raw or args.workdir):
        print("seo_lighthouse: --pagespeed does not combine with --from-json, --keep-raw or --workdir",
              file=sys.stderr)
        return EXIT_USAGE
    if args.runs is None:
        args.runs = PSI_DEFAULT_RUNS if args.pagespeed else DEFAULT_RUNS
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
        if args.pagespeed:
            for url in args.urls:
                host = urlparse(url).hostname or ""
                if not is_public_host(host):
                    print(f"seo_lighthouse: {host!r} is not a public host (a local or private name or address, "
                          "or it does not resolve); Google's servers cannot reach it "
                          "(use the local mode without --pagespeed)", file=sys.stderr)
                    return EXIT_USAGE
            endpoint = os.environ.get(PSI_ENDPOINT_ENV, "").strip() or PSI_ENDPOINT
            override_host = "" if endpoint == PSI_ENDPOINT else (urlparse(endpoint).netloc or endpoint)
            target = f"the endpoint {override_host} ({PSI_ENDPOINT_ENV} override)" if override_host \
                else "Google PageSpeed Insights"
            print(f"seo_lighthouse: sending {len(args.urls)} URL(s) to {target} "
                  f"({PSI_KEY_ENV} {'set' if os.environ.get(PSI_KEY_ENV) else 'not set'})", file=sys.stderr)
            results, version = measure_pagespeed(args.urls, args.runs, args.form_factor, os.environ, args.timeout)
            meta = {"version": version or "(PageSpeed Insights)", "form_factor": args.form_factor,
                    "source": "pagespeed", "endpoint_host": override_host}
            return finish(args, results, meta)
        if not args.workdir and not Path(args.root).is_dir():
            print(f"seo_lighthouse: --root {args.root} is not an existing folder", file=sys.stderr)
            return EXIT_USAGE
        workdir = Path(args.workdir) if args.workdir else Path(args.root) / default_workdir()
        try:
            results = measure(args.urls, args.runs, workdir.resolve(), args.keep_raw, args.timeout,
                              args.form_factor, os.environ)
        except ToolMissing as exc:
            print(f"seo_lighthouse: {exc}", file=sys.stderr)
            return EXIT_MISSING_TOOL
        except UsageError as exc:
            print(f"seo_lighthouse: {exc}", file=sys.stderr)
            return EXIT_USAGE
    return finish(args, results, meta)


def finish(args: argparse.Namespace, results: Sequence[UrlResult], meta: Mapping[str, str]) -> int:
    if args.json:
        payload = {"lighthouse_version": meta.get("version") if meta.get("source") == "pagespeed" else LIGHTHOUSE_VERSION,
                   "source": meta.get("source", "local"), "target": "100, or every deviation justified",
                   "results": [asdict(r) for r in results]}
        if meta.get("source") == "pagespeed":
            payload["note"] = (f"measured through the endpoint {meta['endpoint_host']} (override), not Google"
                               if meta.get("endpoint_host")
                               else "measured by Google PageSpeed Insights; the URLs were sent to Google")
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(render_text(results, meta))
    return exit_code(results)


if __name__ == "__main__":
    sys.exit(main())
