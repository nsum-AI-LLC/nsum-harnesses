#!/usr/bin/env python3
"""SessionStart hook — map session id -> claude pid, and retire a legacy process.

WHY THIS EXISTS (BW-4994, 2026-09-04)

A usage limit does not kill the `claude` process. It only makes every request
fail: the process, its terminal window and its child processes all survive,
appending nothing. That quiet transcript is what the relaunch supervisor's
watchdog detects as a "death" — so when the limit resets and the supervisor
relaunches the session, the ORIGINAL process is very often still sitting there.
Measured on 2026-09-04: session 22e943e2 hit a session limit and was still the
same live pid 4h12m later, alongside the relaunch the supervisor had opened.

That was untidy under the old `/pickup` relaunch (two processes, two different
session ids). It is a correctness problem under the resume relaunch, because
`claude --resume <id>` against a session whose process is still alive starts a
COPY — two processes sharing one session id and one transcript.

The fix is this registry plus a retirement step, and it deliberately does NOT
try to reuse the surviving process. Waking the old window in place would be
elegant exactly when the wait is short, and would fail exactly when it is long:
a weekly limit resets in days, by which time the window is almost certainly
gone. Launching fresh is robust in both directions, so the pid map is used to
RETIRE the legacy process rather than to revive it.

WHAT IT DOES, each SessionStart:
  1. Resolve this session's own `claude` pid by walking up the process tree.
  2. Kill any OTHER live process registered under the SAME session id.
  3. Record this session's pid, and prune entries that are no longer alive.

A brand-new session id has no prior entry, so step 2 is a no-op for it; the step
only ever fires for a resumed session, which is precisely the double-owner case.

SAFETY. This hook sends signals, so every kill is gated on ALL of:
  * the target is not this process, and not an ancestor of it;
  * the target is still alive AND its command is `claude` (not a recycled pid);
  * the target's start time still matches the one recorded at registration —
    the strong pid-reuse guard, since a recycled pid gets a new start time;
  * the target was registered BEFORE this process started.
Anything ambiguous is left alone: a stray surviving session is a nuisance, but
killing an unrelated process is a real loss. Every decision is logged.
"""

import json
import os
import signal
import subprocess
import sys
import time

# Directory names of earlier installs, checked before the default so an
# in-place upgrade keeps a running job's specs, log and history where they
# are. "willcall-relaunch" is the name this originally shipped under.
LEGACY_ROOT_NAMES = ("willcall-relaunch",)


def _relaunch_root():
    """Where the supervisor keeps its state — this hook must write where it reads.

    Mirrors relaunch_common.relaunch_root(). Duplicated rather than imported
    because a hook has to run standalone from `.claude/hooks/`, with no
    dependency on the supervisor being installed at all. Order: explicit
    override, then an EXISTING legacy install (so an in-place upgrade keeps
    writing where the supervisor reads), then the generic default.
    """
    home = os.path.expanduser("~")
    override = os.environ.get("CLAUDE_RELAUNCH_ROOT")
    if override:
        return override
    for legacy in LEGACY_ROOT_NAMES:
        candidate = os.path.join(home, ".claude", legacy)
        if os.path.isdir(candidate):
            return candidate
    return os.path.join(home, ".claude", "claude-relaunch")


ROOT = _relaunch_root()
REGISTRY_PATH = os.path.join(ROOT, "session-pids.json")
LOG_PATH = os.path.join(ROOT, "log.jsonl")

MAX_WALK_DEPTH = 12
# Entries older than this with a dead pid are dropped, so the file cannot grow
# without bound as sessions come and go.
PRUNE_AFTER_SECONDS = 14 * 86400
# How long to let a SIGTERM'd process exit before escalating.
TERM_GRACE_SECONDS = 3.0
TERM_POLL_SECONDS = 0.2


def log(event, **fields):
    """Append to the supervisor's own log, so relaunch and retirement read as
    one story rather than two."""
    row = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "event": event, **fields}
    try:
        os.makedirs(ROOT, exist_ok=True)
        with open(LOG_PATH, "a") as f:
            f.write(json.dumps(row) + "\n")
    except OSError:
        pass  # a hook must never fail the session it is starting


def ps_field(pid, fmt):
    """One `ps -o <fmt>=` field for a pid, or None if the process is gone."""
    try:
        out = subprocess.run(["ps", "-p", str(pid), "-o", fmt + "="],
                             capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    value = out.stdout.strip()
    return value or None


def proc_identity(pid):
    """(command basename, start time) — the pair that identifies a process.

    Start time is what makes this safe against pid reuse: the OS recycles pid
    numbers, but a recycled pid has a different start instant.
    """
    comm = ps_field(pid, "comm")
    if comm is None:
        return None, None
    lstart = ps_field(pid, "lstart")
    return os.path.basename(comm), lstart


def is_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, owned by someone else — still "alive"
    except (OverflowError, ValueError):
        return False


def ancestor_pids(pid):
    """Every pid between this one and init, so we can never signal our own tree."""
    chain = set()
    current = pid
    for _ in range(MAX_WALK_DEPTH):
        chain.add(current)
        ppid = ps_field(current, "ppid")
        if not ppid:
            break
        try:
            current = int(ppid)
        except ValueError:
            break
        if current <= 1:
            break
    return chain


def find_claude_pid(start_pid):
    """Walk up from this hook to the `claude` process that owns the session.

    A hook runs as a grandchild of the client (hook -> shell -> claude), and the
    client's own argv does NOT contain its session id — it names the session it
    was told to pick up, if any. So the process tree, not argv, is the link.
    """
    current = start_pid
    for _ in range(MAX_WALK_DEPTH):
        comm, _ = proc_identity(current)
        if comm == "claude":
            return current
        ppid = ps_field(current, "ppid")
        if not ppid:
            return None
        try:
            current = int(ppid)
        except ValueError:
            return None
        if current <= 1:
            return None
    return None


def load_registry():
    try:
        with open(REGISTRY_PATH) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError, ValueError):
        return {}


def save_registry(registry):
    try:
        os.makedirs(ROOT, exist_ok=True)
        tmp = REGISTRY_PATH + ".tmp"
        with open(tmp, "w") as f:
            json.dump(registry, f, indent=1)
        os.replace(tmp, REGISTRY_PATH)
    except OSError as exc:
        log("session_registry_write_failed", error=str(exc))


def retire(entry, my_pid, my_ancestors, session_id):
    """Kill one legacy process, or explain why we refused to.

    Returns True when the process is gone afterwards (killed, or already dead).
    """
    pid = entry.get("pid")
    if not isinstance(pid, int):
        return True  # malformed entry: drop it
    if pid == my_pid:
        return False  # that's us — keep the entry, obviously do not signal
    if pid in my_ancestors:
        log("legacy_kill_refused", session_id=session_id, pid=pid,
            reason="pid is an ancestor of this session")
        return False
    if not is_alive(pid):
        log("legacy_already_gone", session_id=session_id, pid=pid)
        return True

    comm, lstart = proc_identity(pid)
    if comm != "claude":
        log("legacy_kill_refused", session_id=session_id, pid=pid,
            reason=f"pid is now {comm!r}, not claude (recycled)")
        return True  # not ours any more; forget it rather than signal it
    recorded = entry.get("lstart")
    if recorded and lstart and recorded != lstart:
        log("legacy_kill_refused", session_id=session_id, pid=pid,
            reason="start time changed (recycled pid)",
            recorded=recorded, observed=lstart)
        return True

    try:
        os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError) as exc:
        log("legacy_kill_failed", session_id=session_id, pid=pid,
            signal="TERM", error=str(exc))
        return False

    waited = 0.0
    while waited < TERM_GRACE_SECONDS:
        if not is_alive(pid):
            log("legacy_retired", session_id=session_id, pid=pid, signal="TERM")
            return True
        time.sleep(TERM_POLL_SECONDS)
        waited += TERM_POLL_SECONDS

    # It ignored SIGTERM. A client stuck at a usage wall can be unresponsive,
    # and leaving it alive is the double-owner bug this hook exists to prevent.
    try:
        os.kill(pid, signal.SIGKILL)
        log("legacy_retired", session_id=session_id, pid=pid, signal="KILL")
        return True
    except (ProcessLookupError, PermissionError, OSError) as exc:
        log("legacy_kill_failed", session_id=session_id, pid=pid,
            signal="KILL", error=str(exc))
        return False


def prune(registry, now):
    """Drop dead pids and long-stale sessions; keep the file small."""
    pruned = {}
    for sid, entries in registry.items():
        if not isinstance(entries, list):
            continue
        kept = []
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get("pid"), int):
                continue
            started = entry.get("started_at", 0)
            if not is_alive(entry["pid"]) and now - started > PRUNE_AFTER_SECONDS:
                continue
            if not is_alive(entry["pid"]):
                continue
            kept.append(entry)
        if kept:
            pruned[sid] = kept
    return pruned


def main():
    # A hook must never break the session it is starting: everything below is
    # best-effort, and any unexpected failure exits 0 with a log line.
    try:
        raw = sys.stdin.read()
    except Exception:
        raw = ""
    try:
        data = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        data = {}

    session_id = (data.get("session_id")
                  or os.environ.get("CLAUDE_CODE_SESSION_ID") or "")
    source = data.get("source") or "unknown"
    if not session_id:
        log("session_registry_skipped", reason="no session id in hook input")
        return 0

    my_pid = find_claude_pid(os.getpid())
    if my_pid is None:
        log("session_registry_skipped", session_id=session_id,
            reason="no claude ancestor found")
        return 0

    my_ancestors = ancestor_pids(os.getpid())
    now = time.time()
    registry = load_registry()

    # Retire any OTHER process still registered under this session id. For a
    # fresh session id there are none, so this is a no-op; it fires only for a
    # resume, which is exactly the case that produces two owners.
    survivors = []
    retired = 0
    for entry in registry.get(session_id, []):
        if not isinstance(entry, dict):
            continue
        if entry.get("pid") == my_pid:
            continue  # our own prior registration for this same process
        if retire(entry, my_pid, my_ancestors, session_id):
            retired += 1
        else:
            survivors.append(entry)

    _, my_lstart = proc_identity(my_pid)
    mine = {
        "pid": my_pid,
        "lstart": my_lstart,
        "started_at": now,
        "source": source,
        "project": data.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR", ""),
        "iterm": os.environ.get("ITERM_SESSION_ID", ""),
    }
    registry = prune(registry, now)
    registry[session_id] = survivors + [mine]
    save_registry(registry)
    log("session_registered", session_id=session_id, pid=my_pid, source=source,
        retired=retired, survivors=len(survivors))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # never fail the session start
        log("session_registry_error", error=str(exc))
        sys.exit(0)
