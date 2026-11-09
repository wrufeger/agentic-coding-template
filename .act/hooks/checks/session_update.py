"""Session start, template awareness: a pulled-without-update `.act/`, the once-a-day lookup of the
template's remote in a detached worker, and the advisories.

Split out of session.py, which keeps the entry point and the order of the sub-steps."""
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
from pathlib import Path
from typing import Optional

import actlib
import manifest

from .background import spawn_detached
from .common import _check_mode
from .state_files import checked_today, mark_checked_today

# ---------------------------------------------------------------------------
# Check 2b — template awareness at session start: a project .act/ that was brought to a clean
# template state by something other than update.py (e.g. a plain `git pull` of the shared history
# some projects still keep from before the lock file recorded a manifest fingerprint), and, at most once a day, whether the template's own
# remote has moved past what .act-lock.json last recorded. Both read-only, both best-effort — see
# refresh_session()'s try/except around each call; neither ever raises out of this function.
# ---------------------------------------------------------------------------

def _manifest_fingerprint(act_dir: Path) -> str:
    """CRLF-folded fingerprint of act_dir/MANIFEST.json, matching what .act-lock.json's
    template.manifest_sha256 is meant to record -- unlike a raw `actlib.sha256_file()` of
    the file, this is unaffected by the checkout's line endings (core.autocrlf), so a MANIFEST.json
    checked out with CRLF on Windows still fingerprints the same as the LF copy that produced the
    recorded hash. Prefers manifest.py's own `manifest_fingerprint()` (added alongside this fix);
    falls back to manifest.py's existing `content_hash()` — which already does the same CRLF
    folding for every other file under .act/ — applied to MANIFEST.json directly, in case that
    function has not landed yet. Returns "" if MANIFEST.json cannot be read at all."""
    fingerprint_fn = getattr(manifest, "manifest_fingerprint", None)
    if callable(fingerprint_fn):
        try:
            return fingerprint_fn(act_dir)
        except Exception:
            pass  # fall through to the content_hash() fallback below
    try:
        return manifest.content_hash(act_dir / "MANIFEST.json")
    except OSError:
        return ""


def _pulled_without_update(root: Path) -> bool:
    """True when .act/ matches its own MANIFEST.json exactly (so not a hand-edit — that is a
    different, already-covered concern, see doctor.py's manifest-drift check) but the fingerprint
    of that MANIFEST.json does not match the one .act-lock.json recorded at the last
    update.py/init.py run (`template.manifest_sha256`) -- the fingerprint that tells a
    project's own regular state apart from one a plain `git pull` (or any other means outside
    update.py) just landed."""
    manifest_path = root / ".act" / "MANIFEST.json"
    if not manifest_path.is_file():
        return False
    try:
        recorded = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(recorded, dict) or manifest.collect_files(root / ".act") != recorded:
        return False  # hand-edited (or unreadable) -- not what this check is looking for
    lock = actlib.read_lock()
    expected = (lock.get("template") or {}).get("manifest_sha256") or ""
    return _manifest_fingerprint(root / ".act") != expected


def _update_check_state_path(root: Path) -> Path:
    return root / ".act-local" / "update-check.json"


_STABLE_TAG_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
_UPDATE_CHANNELS = ("release", "latest")


def _ls_remote_output(root: Path, source: str, patterns: list[str]) -> Optional[str]:
    """`git ls-remote -- <source> <patterns>` as text, None when it failed, timed out or the source
    is not a git remote/repo. Output goes to a real temp file, not a pipe -- the reason is
    written out at _remote_update_available below. GIT_TERMINAL_PROMPT/GCM_INTERACTIVE/
    GIT_SSH_COMMAND keep git from ever pausing for a credential prompt or a slow ssh handshake in an
    unattended background process."""
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GCM_INTERACTIVE"] = "never"
    env.setdefault("GIT_SSH_COMMAND", "ssh -o BatchMode=yes -o ConnectTimeout=3")
    # never a user value here: a source such as `ext::<command>` must not start a program
    env["GIT_ALLOW_PROTOCOL"] = "file:git:http:https:ssh"
    # The output folder lives under the project's .act-local/tmp/ and is removed again with retries:
    # on Windows a git child can still hold a file open after the timeout, and a failing cleanup must
    # not raise. git itself runs in `root`, never in the folder.
    with actlib.scratch_dir("update-check", root) as tmp_dir:
        out_path = tmp_dir / "ls-remote.out"
        try:
            with open(out_path, "wb") as out_file:
                result = subprocess.run(
                    ["git", "ls-remote", "--", source, *patterns],
                    cwd=root, stdout=out_file, stderr=subprocess.DEVNULL,
                    timeout=5, env=env,
                    # no console window for git.exe on Windows, where the worker has none
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            if result.returncode != 0:
                return None
            return out_path.read_text(encoding="utf-8", errors="replace").strip()
        except (OSError, subprocess.TimeoutExpired):
            return None


def _update_channel(root: Path) -> str:
    """`update-channel` from docs/ai/config.md: "release" (the default, also for a missing or
    unusable value) or "latest"."""
    value = actlib.read_config(root).get("update-channel", "").strip().strip("`").lower()
    return value if value in _UPDATE_CHANNELS else "release"


def _update_channel_is_default(root: Path) -> bool:
    """True when docs/ai/config.md names no `update-channel` at all, i.e. `release` only by default.
    An unusable value is not the default: it counts like `--channel release`."""
    return not actlib.read_config(root).get("update-channel", "").strip().strip("`")


def _update_channel_follows_tip_without_tags(root: Path) -> bool:
    """True when a source without any release tag is followed at its tip, as update.py does: for the
    default and for `release` in docs/ai/config.md (init writes it into every new project). An
    unusable value counts like `--channel release` and never falls back."""
    return actlib.read_config(root).get("update-channel", "").strip().strip("`").lower() in ("", "release")


def _version_tuple(text: str) -> Optional[tuple[int, int, int]]:
    match = _STABLE_TAG_RE.match(text.strip())
    return (int(match.group(1)), int(match.group(2)), int(match.group(3))) if match else None


def _remote_release_available(root: Path) -> Optional[dict]:
    """The newest stable release tag (vX.Y.Z or X.Y.Z, no pre-release) of the source as
    {"release": tag, "release_commit": commit}; {} when the source answered but has no such tag; None
    when it could not be read -- silent in both cases, like _remote_update_available. Same
    constraints: only called from the background worker, one `git ls-remote` with the same 5 s limit."""
    source = (actlib.read_lock().get("template") or {}).get("source") or ""
    if not source:
        return None
    output = _ls_remote_output(root, source, ["refs/tags/*"])
    if output is None:
        return None
    commits: dict[str, str] = {}
    peeled: dict[str, str] = {}
    for line in output.splitlines():
        commit, _, name = line.partition("\t")
        name = name.strip()
        if not name.startswith("refs/tags/"):
            continue
        tag = name[len("refs/tags/"):]
        if tag.endswith("^{}"):
            peeled[tag[:-3]] = commit
        else:
            commits[tag] = commit
    best: Optional[tuple[tuple[int, int, int], str, str]] = None
    for tag, commit in commits.items():
        version = _version_tuple(tag)
        if version is not None and (best is None or version > best[0]):
            best = (version, tag, peeled.get(tag, commit))
    if best is None:
        return {}
    return {"release": best[1], "release_commit": best[2]}


def _folder_source_result(root: Path) -> Optional[dict]:
    """The update-check result for a recorded source that is a plain folder without git: {} when the
    folder's manifest is the one the project last applied (nothing pending, the caller drops an old
    result), a tip-style result keyed by the manifest fingerprint when it differs, None when the
    folder cannot be judged (not a folder, git after all, no manifest, nothing applied yet)."""
    template = actlib.read_lock().get("template") or {}
    source = str(template.get("source") or "")
    # the source's own fingerprint recorded at update time; a lock from before that falls back to
    # the project manifest's hash, which matches only while the source's manifest is current
    applied = str(template.get("source_fingerprint") or template.get("manifest_sha256") or "")
    if not source or not applied:
        return None
    folder = Path(root, source)
    if not folder.is_dir() or (folder / ".git").exists() or not (folder / ".act" / "MANIFEST.json").is_file():
        return None
    offered = _manifest_fingerprint(folder / ".act")
    if not offered:
        return None
    if offered == applied:
        return {}
    return {"channel": "latest", "remote_commit": offered, "tip_fallback": True, "label": offered[:7],
            "installed_commit": _locked_commit(root), "folder_source": True}


def _remote_update_available(root: Path) -> Optional[str]:
    """None if the check could not be made at all (no source/commit recorded, no network, the
    source is not a git remote/repo, or it took too long) -- always silent in that case, never a
    reported error (dispatch.py's docstring: a SessionStart check fails open). Otherwise the
    remote's current commit hash (which may equal the lock's own commit -- the caller decides
    what that means; see _run_update_check_worker).

    Only ever called from _run_update_check_worker(), i.e. inside the detached background
    process _spawn_update_check_worker() starts -- never directly from the SessionStart hook, so
    however long `git ls-remote` actually takes here never delays a session (see the header
    comment above _pulled_without_update).

    stdout/stderr go to a real temp file, not a pipe: `subprocess.run(capture_output=True, ...)`
    was measured at 21s against an unreachable address on Windows even with `timeout=5`, because
    a grandchild process git spawns (e.g. for the ssh transport) can keep the write end of the
    pipe open past the point `timeout` kills the immediate `git` process, and `communicate()`
    then blocks reading from that still-open pipe until the grandchild itself gives up. Waiting
    on a real file's process exit status has no such pipe to drain, so the timeout is enforced
    as written. GIT_TERMINAL_PROMPT/GCM_INTERACTIVE/GIT_SSH_COMMAND keep git from ever pausing
    for a credential prompt or a slow ssh handshake in an unattended background process."""
    lock = actlib.read_lock()
    template = lock.get("template") or {}
    source = template.get("source") or ""
    commit = template.get("commit") or ""
    if not source or not commit:
        return None
    output = _ls_remote_output(root, source, ["HEAD"])
    if not output:
        return None
    remote_commit = output.split()[0].strip()
    return remote_commit or None


def _update_check_result_path(root: Path) -> Path:
    return root / ".act-local" / "update-check-result.json"


def _pending_update_note(root: Path, state: Optional[dict] = None) -> Optional[str]:
    """The session-start note for a template update the background check found earlier
    (.act-local/update-check-result.json, written by _run_update_check_worker). The result stays
    until the project has caught up: every session start repeats the note while the update is
    pending, and the file is removed only once the lock says the state is installed. The decision
    is actlib.pending_update()'s -- the lock and the channel are re-read now, not trusted from
    whatever the worker saw -- shared with the board and the status line. Fills `state["update"]` with
    the value to show for the human line. Silent on any I/O problem."""
    info = actlib.pending_update(root)
    if info is None:
        return None
    if not info["pending"]:
        try:
            if actlib.local_write_ok(root, actlib.update_result_path(root)):
                actlib.update_result_path(root).unlink()
        except OSError:
            pass
        if info.get("stale"):
            # the lock moved since the check: look again at this start instead of tomorrow
            try:
                if actlib.local_write_ok(root, _update_check_state_path(root)):
                    _update_check_state_path(root).unlink()
            except OSError:
                pass
        return None
    if state is not None:
        state["update"] = info["label"]
    if info["release"]:
        return (f"[act] note: template release {info['release']} available "
                f"(installed {info['installed'] or 'unknown'}) -- run `python .act/scripts/update.py`")
    return "[act] note: a template update is available -- run `python .act/scripts/update.py`"


def _commit_day(repo: Path, commit: str) -> Optional[str]:
    """The committer date of `commit` in `repo`, read locally (actlib.commit_day)."""
    return actlib.commit_day(repo, commit)


def _remote_commit_label(root: Path, commit: str) -> str:
    """What the status line and the board show for a remote tip: its date or its short hash
    (actlib.remote_commit_label, shared with update.py)."""
    return actlib.remote_commit_label(root, commit)


def _locked_commit(root: Optional[Path] = None) -> str:
    """The template commit the lock records now -- stored with a tip result, so a later start can tell
    that the lock moved on since the check (actlib.pending_update's `stale`)."""
    return actlib.locked_commit(root or actlib.repo_root())


def _run_update_check_worker(root: Path) -> int:
    """Body of the detached background process _spawn_update_check_worker() launches: the update
    lookup (_run_update_lookup) and, side by side in a thread, the lookup of the template author's
    advisories (_run_advisory_lookup). Side by side because each waits up to 5 s on an unreachable
    source; one after the other, the process would take twice as long. Each is isolated from the other
    and from the SessionStart hook; always exits 0 -- nothing reads this process's own exit code, and
    every exception here must stay inside this process."""
    advisories = threading.Thread(target=_run_advisory_lookup, args=(root,))
    advisories.start()
    try:
        _run_update_lookup(root)
    except Exception:
        pass
    advisories.join()
    return 0


def _run_advisory_lookup(root: Path) -> None:
    """The second job of the daily background process: ask the template source for its `advisories`
    branch and refresh the cache (advisory.refresh(): its own ls-remote and, only when the branch moved,
    a fetch into .act-local/advisories.git). Uses advisory.py's own git helper (same 5 s limit and
    no-prompt environment, plus a fixed protocol list the user's environment cannot widen).
    `advisory-check: off` does nothing. Never raises; only the next session start sees the result."""
    try:
        import advisory  # deferred like update: a broken advisory.py must not touch the update check
        advisory.refresh(root)
    except Exception:
        pass


def _run_update_lookup(root: Path) -> None:
    """The update half of the background process: the actual
    network lookup, isolated from the SessionStart hook so its result can only ever help the
    *next* session, never delay this one. Writes update-check-result.json with the release or the remote
    commit found, plus a `label` to show (the release without its `v`, the commit's date or its short
    hash); leaves any existing file alone when the lookup was inconclusive (None), so a
    stale-but-valid earlier result is not clobbered by a run that itself couldn't tell. Whether
    that remote commit still means "update available" is decided later, by
    _pending_update_note() against the lock as it stands then -- not here, since this
    process's result may sit across more than one later `update.py` run. Exceptions are the
    caller's to swallow."""
    try:
        if _update_channel(root) == "release":
            found = _remote_release_available(root)
            result = ({"channel": "release", **found, "label": str(found["release"]).lstrip("vV")}
                      if found else None)
            if found == {} and _update_channel_follows_tip_without_tags(root):
                # the default or `release` in config.md on a source without any release tag (a local
                # copy, a young repository): follow the tip, as update.py does in the same case
                remote_commit = _remote_update_available(root)
                result = ({"channel": "latest", "remote_commit": remote_commit, "tip_fallback": True,
                           "label": _remote_commit_label(root, remote_commit),
                           "installed_commit": _locked_commit(root)}
                          if remote_commit else None)
            elif found is None and _update_channel_follows_tip_without_tags(root):
                # a source folder without git has no tags and no tip commit: compare its manifest
                # with the one the project last applied (update.py takes such a folder as it is)
                result = _folder_source_result(root)
                if result == {}:
                    actlib.record_update_result(root, None)
                    return
        else:
            remote_commit = _remote_update_available(root)
            result = ({"channel": "latest", "remote_commit": remote_commit,
                       "label": _remote_commit_label(root, remote_commit),
                       "installed_commit": _locked_commit(root)} if remote_commit else None)
    except Exception:
        return
    if result is None:
        return
    actlib.record_update_result(root, result)


def _spawn_update_check_worker(root: Path) -> None:
    """Fire-and-forget: starts _run_update_check_worker(root) as a detached background process (the
    "_update-check-worker" event of dispatch.main(), see background.spawn_detached) and returns at once.
    Best-effort: a failure to spawn is silent, same as every other note in this check."""
    if not actlib.local_write_ok(root, root / ".act-local" / "update-check.json"):
        return  # the worker leaves its result below .act-local: not through a link
    spawn_detached(root, "_update-check-worker")


def _advisory_notes(root: Path, config: dict[str, str], state: dict) -> list[str]:
    """The template author's warnings that apply to this project (advisory.py), from files -- no
    network; git only for the read-only history search before a critical advisory's todo is filed (a few
    seconds at most); the background worker keeps the cache current. Puts the visible lines (critical
    first) in `state["advisory"]` for the human line and returns the notes for the model. A critical one
    also gets its inbox todo, once, unless `session-start-refresh` is off. `advisory-check: off` shows
    nothing. Never raises."""
    try:
        import advisory  # deferred like update: a broken advisory.py must not end the session
        file_todos = _check_mode(config, "session-start-refresh", default="block") != "off"
        report = advisory.session_report(root, file_todos=file_todos)
    except Exception:
        return []
    if report.lines:
        state["advisory"] = report.lines
    return report.notes


def _check_update_awareness(root: Path, config: dict[str, str],
                            state: Optional[dict] = None) -> tuple[list[str], list[str]]:
    """Check 2b's two notes, gated by the single `update-check` row (docs/ai/config.md § Checks,
    default "block" == on; "off" skips both notes and never spawns the background worker below).

    Returns (pre_notes, post_notes) -- pre_notes belong before the fixed-format status line,
    post_notes after it (dispatch.py's docstring / SessionStart output format): the pulled-
    without-update note is local, cheap and synchronous, so it stays a pre_note like before; the
    remote "update available" note is always a *previous* run's finding (see
    _spawn_update_check_worker below), so it prints as a postscript after the status line rather
    than ahead of it. It repeats at every start until the update is installed; `state["update"]`
    then carries the value to show for the human line.

    The remote lookup itself is throttled to once a day via .act-local/update-check.json
    (gitignored, per-checkout): when not yet checked today, this kicks off a detached background
    process (_spawn_update_check_worker) and marks today as checked immediately, without waiting
    for that process -- its result, if any, is picked up by _pending_update_note() on a
    later SessionStart. Never raises."""
    mode = _check_mode(config, "update-check", default="block")
    if mode == "off":
        return [], []
    pre_notes: list[str] = []
    post_notes: list[str] = []
    if _pulled_without_update(root):
        pre_notes.append("[act] note: .act/ was pulled in without update.py -- run `python .act/scripts/update.py` (or --catch-up) to finish it")
    pending = _pending_update_note(root, state)
    if pending:
        post_notes.append(pending)
    if not checked_today(_update_check_state_path(root)):
        mark_checked_today(root, _update_check_state_path(root))
        _spawn_update_check_worker(root)
    return pre_notes, post_notes
