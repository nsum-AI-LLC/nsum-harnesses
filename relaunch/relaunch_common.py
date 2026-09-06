#!/usr/bin/env python3
"""relaunch_common — limit classification, reset parsing, and availability probing.

Shared by claude_relaunch_supervisor (the launchd tick) and
claude_write_relaunch_spec (the wind-down hook).

EVERYTHING HERE IS GROUNDED IN CLAUDE CODE'S OWN RENDERER, read out of the shipped
binary (2.1.260) rather than induced from whatever deaths happened to be on disk.
That distinction is the whole point of this module: the previous parser was induced
from two SESSION-limit deaths (2026-07-03, 2026-08-30) and therefore silently could
not read the WEEKLY form. On 2026-09-01 a weekly kill logged
`watchdog_no_reset_time` every two minutes for three days and relaunched nothing.

LIMIT WORDING — the client's own map, verbatim:

    five_hour                  -> "session limit"
    seven_day                  -> "weekly limit"
    seven_day_opus             -> "Opus limit"
    seven_day_sonnet           -> "Sonnet limit"
    seven_day_overage_included -> "Fable limit"
    overage                    -> "usage credit limit"

rendered as "You've hit your <name> · resets <when>", plus the mid-session
variants "You've reached your Fable limit" and "You're out of usage credits".
The old marker enumerated only (session|monthly spend|usage|weekly), so it was
blind to the Opus/Sonnet/Fable/credit forms — a blindness that got WORSE when the
account default became Fable.

RESET WORDING — the formatter picks ONE of two shapes, by horizon:

    <= 24h out:  "3am"  /  "3:20am"                  (toLocaleTimeString, hour12)
    >  24h out:  "Sep 4 at 3am" / "Sep 4 at 3:20am"  (toLocaleString month+day)
                 "Sep 4, 2027 at 3am"                (year added across a boundary)

each optionally suffixed " (America/Los_Angeles)". There is NO weekday form and no
ISO form. Minutes are omitted when zero. Both shapes are handled below; they are
lexically disjoint (the dated one never starts with a digit after "resets"), so
trying dated-then-bare cannot mis-parse.

WHY A PROBE EXISTS AT ALL. Quota state lives server-side and reaches a client only
on an API response — there is no local file and no free endpoint that reports it
while nothing is running. So "has the limit lifted?" is only answerable by making a
request. It does NOT have to be a meaningful one: the minimum accepted request is a
1-token turn with the system prompt replaced, tools off and settings ignored,
measured at ~14.4k cache-read tokens and ~2s. We use only whether it was ACCEPTED,
never its text.

WHAT A PROBE ACTUALLY COSTS. Nothing in dollars: this account authenticates by
subscription, and Claude Code's `total_cost_usd` / `costUSD` are estimates priced
at built-in LIST rates (`costBasis: "list"`) for the API-billing path — telemetry,
not a charge. Extra usage is org-disabled here, so there is no spill-to-paid path
either; a request either fits the plan or is refused. The real currency is the
rate-limit windows, and there the draw is ~1,440 weighted tokens per probe (cache
reads x0.1, the claude_usage_meter formula) against a 5h ceiling calibrated at
235M — 0.0006% of a window. Better still, a probe against a SHUT pool is rejected
before inference and so draws nothing at all: the pool is touched only on the one
probe that succeeds, after which the spec launches and polling stops.

WHY THE SUPERVISOR MUST COVER THIS AT ALL. Claude Code's own auto-continue refuses
any horizon beyond 24 hours ("the usage limit now resets more than 24 hours out, so
this task will not resume on its own"). A weekly reset is days out. The weekly case
is therefore the one case the product deliberately does not cover.
"""

import datetime
import time
import getpass
import json
import os
import re
import subprocess
import tempfile
import zoneinfo

HOME = os.path.expanduser("~")


# Directory names of earlier installs, checked before the default so an
# in-place upgrade keeps a running job's specs, log and history where they
# are. "willcall-relaunch" is the name this originally shipped under.
LEGACY_ROOT_NAMES = ("willcall-relaunch",)


def relaunch_root():
    """Where the supervisor keeps its specs, log and state.

    Resolution order — the middle entry is the one that matters when upgrading:
    an explicit override, then any EXISTING legacy install (so a machine set up
    before this was generalized keeps its running launchd job, its pending specs
    and its history exactly where they are), then the generic default.
    """
    override = os.environ.get("CLAUDE_RELAUNCH_ROOT")
    if override:
        return override
    for legacy in LEGACY_ROOT_NAMES:
        candidate = os.path.join(HOME, ".claude", legacy)
        if os.path.isdir(candidate):
            return candidate
    return os.path.join(HOME, ".claude", "claude-relaunch")


def resolve_project_slug(slug):
    """Rebuild a filesystem path from a Claude Code project-directory slug.

    The slug replaces '/' with '-', which is LOSSY: a dash inside a real path
    segment is indistinguishable from a separator, and `.claude` appears as an
    empty part (the '/.' becomes '--'). So resolve greedily against directories
    that actually exist, longest run first, rather than guessing. This is what
    lets the supervisor serve ANY project instead of a hardcoded one, and it
    resolves worktree namespaces as a side effect.
    """
    parts = slug.lstrip("-").split("-")
    path = ""
    i = 0
    while i < len(parts):
        prefix = "/"
        if parts[i] == "":
            # An empty part means the next segment began with a dot.
            i += 1
            if i >= len(parts):
                break
            prefix = "/."
        for j in range(len(parts), i, -1):
            candidate = path + prefix + "-".join(parts[i:j])
            if os.path.isdir(candidate):
                path, i = candidate, j
                break
        else:
            path += prefix + parts[i]
            i += 1
    return path or "/"


ROOT = relaunch_root()
RATE_LIMITS_PATH = os.path.join(ROOT, "rate-limits.json")
PROBE_CWD = os.path.join(ROOT, "probe-cwd")

UTC = datetime.timezone.utc

# ---------------------------------------------------------------- classification

_APOS = r"['‘’`]?"

# Non-greedy name capture: "usage credit limit" must yield "usage credit", not
# "usage" (which would leave " credit limit" unmatched and fail the \s+limit tail).
LIMIT_RE = re.compile(
    rf"[Yy]ou{_APOS}ve\s+(?:hit|reached)\s+your\s+"
    rf"(?P<name>[A-Za-z][A-Za-z ]{{0,22}}?)\s+limit")
OUT_OF_CREDITS_RE = re.compile(rf"[Yy]ou{_APOS}re\s+out\s+of\s+usage\s+credits")
GENERIC_429_RE = re.compile(
    r"error type rate_limit|HTTP 429|\"type\"\s*:\s*\"rate_limit_error\"", re.I)

LIMIT_NAME_TO_KIND = {
    "session": "session",           # five_hour
    "weekly": "weekly",             # seven_day
    "opus": "opus",                 # seven_day_opus
    "sonnet": "sonnet",             # seven_day_sonnet
    "fable": "fable",               # seven_day_overage_included
    "usage credit": "credits",      # overage
    "monthly spend": "credits",
}

# Kinds that gate EVERY model on the account. Only these are worth waiting on; a
# model-scoped limit is escaped by switching tier, not by waiting.
#
# `credits` — the monthly spend cap — is deliberately NOT here, against the
# intuition that a spend cap must gate everything. Measured 2026-09-05: one
# account returned "You've hit your monthly spend limit" on Opus while Sonnet
# subagents ran on that same account minutes later. The cap binds only on a
# request that needs OVERAGE, so a model whose included pool still has room
# never reaches it. Classing it as shared would take a working account out of
# rotation, which fails in the more expensive direction than leaving it in.
#
# What would settle it: a credits rejection on a model whose own weekly pool is
# known to be unexhausted. Until then this stays where the evidence puts it.
SHARED_POOL_KINDS = frozenset({"session", "weekly"})

# NOTE: there is deliberately no tier-preference table here any more. Choosing
# which model a relaunch runs on is the CLIENT's job, from settings.json's
# `model` + `fallbackModel`; the supervisor names a model only when probing,
# where a canary has to ask about one specific pool. A helper that picked a
# relaunch tier used to live here and was removed on 2026-09-04 — it overrode
# the account's Fable-then-Opus policy and pinned relaunches to Opus.


def is_limit_death(text):
    """Does this text carry ANY usage-limit rejection wording?"""
    return bool(LIMIT_RE.search(text)
                or OUT_OF_CREDITS_RE.search(text)
                or GENERIC_429_RE.search(text))


def classify_limit(text):
    """(kind, rendered_name). kind is None when the wording is a limit we cannot
    name — still a death, just not one we can reason about by tier."""
    m = LIMIT_RE.search(text)
    if m:
        name = " ".join(m.group("name").split()).lower()
        return LIMIT_NAME_TO_KIND.get(name), name
    if OUT_OF_CREDITS_RE.search(text):
        return "credits", "usage credits"
    if GENERIC_429_RE.search(text):
        return None, None
    return None, None


def waits_for_reset(kind):
    """A shared pool must be waited out. A model-scoped one is escaped NOW by
    relaunching and letting the client's fallbackModel chain pick an open tier —
    waiting days for Fable while Opus is open is exactly the dormancy this
    supervisor exists to prevent."""
    return kind in SHARED_POOL_KINDS or kind is None


def probe_model_for(kind, relaunch_model=None):
    """Cheapest model that is a VALID canary for the exhausted pool.

    A shared pool gates haiku too, so haiku is both correct and ~10x cheaper.
    A model-scoped pool must be probed on its own model or the probe is a
    guaranteed false positive.
    """
    if kind in SHARED_POOL_KINDS:
        return "haiku"
    if kind in ("opus", "sonnet", "fable"):
        return kind
    return relaunch_model or "haiku"


# ------------------------------------------------------------- reset parsing

_MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
           "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}

_TZ = r"(?:\s*\(?(?P<tz>[A-Za-z_]+(?:/[A-Za-z_]+)+)\)?)?"
_CLOCK = r"(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*(?P<ampm>[AaPp]\.?[Mm]\.?)?"

RESET_DATED_RE = re.compile(
    r"resets\s+(?P<mon>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+"
    r"(?P<day>\d{1,2})(?:,\s*(?P<year>\d{4}))?\s+at\s+" + _CLOCK + _TZ)
RESET_BARE_RE = re.compile(r"resets\s+(?:at\s+)?" + _CLOCK + _TZ)


def _zone(name):
    if name:
        try:
            return zoneinfo.ZoneInfo(name)
        except Exception:
            pass
    # No zone named: the client omits it only when it would be redundant with the
    # machine's own zone, so local is the right assumption, never UTC.
    return datetime.datetime.now().astimezone().tzinfo


def _clock(m):
    hour = int(m.group("hour"))
    minute = int(m.group("minute") or 0)
    ampm = (m.group("ampm") or "").replace(".", "").lower()
    if ampm:
        hour %= 12
        if ampm.startswith("p"):
            hour += 12
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return hour, minute


def parse_reset(text, anchor_epoch):
    """The reset instant the text names, as aware UTC, or None.

    Anchored at `anchor_epoch` (the death moment), never at "now": if the
    supervisor first reads a death long after it happened, a reset already in the
    past yields a past instant, i.e. relaunch immediately — which is correct.
    """
    m = RESET_DATED_RE.search(text)
    if m:
        return _dated(m, anchor_epoch)
    m = RESET_BARE_RE.search(text)
    if m:
        return _bare(m, anchor_epoch)
    return None


def _dated(m, anchor_epoch):
    tz = _zone(m.group("tz"))
    clock = _clock(m)
    if clock is None:
        return None
    hour, minute = clock
    anchor = datetime.datetime.fromtimestamp(anchor_epoch, tz)
    year = int(m.group("year")) if m.group("year") else anchor.year
    try:
        cand = datetime.datetime(year, _MONTHS[m.group("mon").lower()[:3]],
                                 int(m.group("day")), hour, minute, tzinfo=tz)
    except (ValueError, KeyError):
        return None
    # The year is printed only when it differs from the CURRENT year, so an
    # omitted year means "this year" — unless the window straddles Dec/Jan, which
    # shows up as a date implausibly far behind the death.
    if m.group("year") is None and cand < anchor - datetime.timedelta(days=1):
        try:
            cand = cand.replace(year=year + 1)
        except ValueError:
            return None
    return cand.astimezone(UTC)


def _bare(m, anchor_epoch):
    """The bare-clock form is only ever emitted for a reset <=24h out, so the next
    occurrence after the death is exactly right — and, unlike the old parser, this
    branch is now the ONLY one that may add a day."""
    tz = _zone(m.group("tz"))
    clock = _clock(m)
    if clock is None:
        return None
    hour, minute = clock
    anchor = datetime.datetime.fromtimestamp(anchor_epoch, tz)
    cand = anchor.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if cand <= anchor:
        cand += datetime.timedelta(days=1)
    return cand.astimezone(UTC)


# ------------------------------------------------- structured limits (statusline)

WINDOW_FOR_KIND = {
    "session": "five_hour",
    "weekly": "seven_day",
    "opus": "seven_day_opus",
    "sonnet": "seven_day_sonnet",
}


def structured_reset(kind, anchor_epoch, max_skew_seconds=1800):
    """Reset instant from the live `rate_limits` block the statusline captured.

    Structured epoch seconds straight from the server beat parsing prose, so this
    is tried FIRST. It is only trusted when the capture brackets the death: an
    older capture describes a window that has since moved.
    """
    try:
        with open(RATE_LIMITS_PATH) as f:
            blob = json.load(f)
    except (OSError, json.JSONDecodeError, ValueError):
        return None
    captured_at = blob.get("captured_at")
    limits = blob.get("rate_limits")
    if not isinstance(captured_at, (int, float)) or not isinstance(limits, dict):
        return None
    if abs(captured_at - anchor_epoch) > max_skew_seconds:
        return None

    window = limits.get(WINDOW_FOR_KIND.get(kind, ""))
    resets_at = window.get("resets_at") if isinstance(window, dict) else None
    if resets_at is None and kind == "fable":
        for entry in limits.get("model_scoped") or []:
            if isinstance(entry, dict) and "fable" in str(
                    entry.get("display_name", "")).lower():
                resets_at = entry.get("resets_at")
                break
    if isinstance(resets_at, str):  # model_scoped renders ISO-8601, not epoch
        try:
            resets_at = datetime.datetime.fromisoformat(
                resets_at.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    if not isinstance(resets_at, (int, float)) or resets_at <= 0:
        return None
    return datetime.datetime.fromtimestamp(resets_at, UTC)


# ------------------------------------------------------------------- the probe

PROBE_TIMEOUT_SECONDS = 120
# The minimum request the CLI will accept, measured at $0.0019 / ~2s: replace the
# system prompt, take no tools, ignore project settings and hooks, one turn, and
# do not persist a transcript. NOTE: --bare is deliberately absent — it skips
# credential loading and every probe comes back "Not logged in", which would read
# as a limit if we were not careful (we are: see the classifier below).
PROBE_ARGS = ["-p", "1",
              "--system-prompt", "Reply: ok",
              "--allowedTools", "",
              "--settings", "{}",
              "--max-turns", "1",
              "--output-format", "json",
              "--no-session-persistence"]

_CLAUDE_CANDIDATES = (
    os.path.join(HOME, ".local", "bin", "claude"),
    "/opt/homebrew/bin/claude",
    "/usr/local/bin/claude",
)


def claude_binary():
    """launchd hands us a minimal PATH, so resolve absolutely before trusting it."""
    for candidate in _CLAUDE_CANDIDATES:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        candidate = os.path.join(directory, "claude")
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def probe_env():
    """The environment the probe needs, asserted rather than inherited.

    Measured 2026-09-03 against the REAL launchd agent environment (captured by
    running /usr/bin/env as a LaunchAgent, not guessed): credential lookup needs
    USER/LOGNAME — without them the CLI finds a token it cannot refresh and
    reports "OAuth session expired and could not be refreshed". launchd does
    supply both today, so this is belt-and-braces; the failure mode it prevents
    is a silent one, where every probe returns indeterminate forever and early
    resets are never noticed again.
    """
    env = os.environ.copy()
    env.setdefault("HOME", HOME)
    try:
        default_user = getpass.getuser()
    except Exception:
        default_user = os.path.basename(HOME)
    if not env.get("USER"):
        env["USER"] = default_user
    if not env.get("LOGNAME"):
        env["LOGNAME"] = env["USER"]
    if not env.get("TMPDIR"):
        env["TMPDIR"] = tempfile.gettempdir()
    exe = claude_binary()
    if exe:  # launchd's PATH omits ~/.local/bin, where the CLI actually lives
        env["PATH"] = os.pathsep.join(
            [os.path.dirname(exe), env.get("PATH", "/usr/bin:/bin")])
    return env


def probe_available(model):
    """(available, detail) — available is True / False / None.

    True  = a request was ACCEPTED, so the pool is open.
    False = rejected with limit wording, so it is still closed.
    None  = indeterminate (no binary, timeout, network, unparseable, any other
            error). NEVER collapse None into either answer: reading a network
            outage as "open" opens terminals into a dead pool, and reading it as
            "closed" reinstates the dormancy this whole change exists to remove.
    """
    exe = claude_binary()
    if exe is None:
        return None, "claude binary not found"
    os.makedirs(PROBE_CWD, exist_ok=True)
    try:
        proc = subprocess.run([exe, "--model", model] + PROBE_ARGS,
                              cwd=PROBE_CWD, capture_output=True, text=True,
                              timeout=PROBE_TIMEOUT_SECONDS, env=probe_env())
    except subprocess.TimeoutExpired:
        return None, "probe timed out"
    except Exception as exc:
        return None, f"probe could not run: {exc}"
    try:
        payload = json.loads(proc.stdout)
    except (json.JSONDecodeError, ValueError):
        return None, f"probe output unparseable (rc={proc.returncode})"
    if not payload.get("is_error"):
        return True, "accepted"
    detail = str(payload.get("result") or "")[:300]
    if is_limit_death(detail):
        return False, detail
    return None, f"non-limit error: {detail}"


# ------------------------------------------------ the account's declared tiers

SETTINGS_PATH = os.path.join(HOME, ".claude", "settings.json")

# The short names both `--model` and `/model` accept. The lookup below is a
# substring test so a fully-qualified id ("claude-opus-5") and an alias
# ("opusplan") resolve to the tier they name; no tier name contains another.
KNOWN_TIERS = ("fable", "opus", "sonnet", "haiku")


def tier_name(value):
    """The short tier a settings value names, or None if it names none."""
    if not isinstance(value, str):
        return None
    lowered = value.strip().lower()
    for tier in KNOWN_TIERS:
        if tier in lowered:
            return tier
    return None


def tier_preference(settings_path=None):
    """The account's declared tier order: `model` first, then `fallbackModel`.

    THE CLIENT DOES NOT APPLY THAT CHAIN TO AN INTERACTIVE SESSION, which is the
    only reason this function has to exist. `claude --help` is explicit on both
    counts: --fallback-model covers a primary that is "overloaded or not
    available", and "(only works with --print)". A usage limit is neither of
    those, and an interactive session is not --print.

    Measured 2026-09-05: three interactive sessions exhausted the Fable pool and
    took five hard stops between them ("You've reached your Fable limit ... switch
    models with /model") with ZERO Opus turns, while settings carried
    `model: opus` and `fallbackModel: ["opus"]`. So a model-scoped limit does not
    resolve itself, and something has to choose the tier.

    The supervisor reads the order the owner declared and applies it; it does not
    invent one. That distinction is the 2026-09-04 lesson — a hardcoded preference
    table here pinned every relaunch to Opus and kept relaunched sessions off
    Fable even when Fable had capacity.
    """
    path = settings_path or SETTINGS_PATH
    try:
        with open(path) as f:
            settings = json.load(f)
    except (OSError, json.JSONDecodeError, ValueError):
        return []
    if not isinstance(settings, dict):
        return []
    declared = [settings.get("model")]
    fallback = settings.get("fallbackModel")
    # Both shapes occur: the CLI flag documents a comma-separated list, and the
    # settings key is written as a JSON array (this account's is ["opus"]).
    if isinstance(fallback, str):
        declared.extend(fallback.split(","))
    elif isinstance(fallback, list):
        declared.extend(fallback)
    order = []
    for value in declared:
        tier = tier_name(value)
        if tier and tier not in order:
            order.append(tier)
    return order


def choose_open_tier(exhausted_kind, preference=None, probe=None):
    """(tier, detail, unknown) — the first declared tier OTHER than the exhausted
    one that a probe finds open, or (None, reason, unknown) when none does.

    Probing is what makes the switch safe to act on: moving a session onto a tier
    that is itself exhausted just relocates the stall, and quota state is only
    knowable by making a request (see WHY A PROBE EXISTS AT ALL, above). An
    indeterminate probe is never read as open.

    `unknown` is True when at least one candidate could not be determined, and it
    exists so the caller does not tell the owner the wrong thing. "Every tier you
    declared is spent" and "a probe could not answer" both leave the switch
    un-made, but only the first is worth acting on — advising someone to widen
    `fallbackModel` because the network blinked is a false alarm, and false alarms
    are how a real one gets ignored. Measured 2026-09-05: three probes inside 40s,
    and the third came back indeterminate while the pool was demonstrably open.
    """
    order = preference if preference is not None else tier_preference()
    probe = probe or probe_available
    candidates = [tier for tier in order if tier != exhausted_kind]
    if not candidates:
        return None, ("no alternative tier declared in settings "
                      f"(order: {order or 'empty'})"), False
    seen = []
    unknown = False
    for tier in candidates:
        available, detail = probe(tier)
        seen.append(f"{tier}={available}")
        if available is True:
            return tier, detail, False
        if available is None:
            unknown = True
    reason = ("could not determine any declared tier" if unknown
              else "every declared tier answered closed")
    return None, f"{reason} (" + ", ".join(seen) + ")", unknown


# --------------------------------------------------- live work under a session

# Every Bash-tool command runs in a shell that sources the session's snapshot, so
# this substring identifies "a command this session is running" and nothing else:
# an MCP server, a pty host and the daemon are children too and must not be read
# as work. Measured 2026-09-05 — the tool's shell is a direct child of `claude`:
#   48628 30148 /bin/zsh -c source ~/.claude/shell-snapshots/snapshot-zsh-*.sh ...
# A BACKGROUNDED command keeps that shell alive until it exits while appending
# NOTHING to the transcript, so transcript quiet does not imply the session has
# stopped working. This is the signal that does.
SHELL_TOOL_SIGNATURE = "shell-snapshots/snapshot"


def process_table():
    """[(pid, ppid, command)] for every live process; [] if ps cannot be read."""
    try:
        proc = subprocess.run(["ps", "-eo", "pid=,ppid=,command="],
                              capture_output=True, text=True, timeout=30)
    except Exception:
        return []
    rows = []
    for line in proc.stdout.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) < 3:
            continue
        try:
            rows.append((int(parts[0]), int(parts[1]), parts[2]))
        except ValueError:
            continue
    return rows


def descendant_pids(pid, table=None):
    """Every live descendant of `pid`, excluding `pid` itself. Cycle-safe."""
    rows = process_table() if table is None else table
    children = {}
    for child, parent, _cmd in rows:
        children.setdefault(parent, []).append(child)
    seen = set()
    queue = list(children.get(pid, []))
    while queue:
        current = queue.pop()
        if current == pid or current in seen:
            continue
        seen.add(current)
        queue.extend(children.get(current, []))
    return seen


def running_tool_shells(pid, table=None):
    """Commands of the Bash-tool shells still running under this session."""
    rows = process_table() if table is None else table
    live = descendant_pids(pid, rows)
    return [cmd for (child, _parent, cmd) in rows
            if child in live and SHELL_TOOL_SIGNATURE in cmd]


# ---------------------------------------------------- the session pid registry

SESSION_PIDS_PATH = os.path.join(ROOT, "session-pids.json")


def _pid_lstart(pid):
    """The kernel's start-time string for a live pid, or None if it is gone."""
    try:
        proc = subprocess.run(["ps", "-o", "lstart=", "-p", str(pid)],
                              capture_output=True, text=True, timeout=10)
    except Exception:
        return None
    return proc.stdout.strip() or None


def live_session_process(session_id, registry_path=None):
    """The registry entry whose process is still THIS session's, or None.

    The registry is written by the session-pid-registry SessionStart hook, which
    exists because a usage limit does not kill the process — it only makes every
    request fail. Liveness is re-derived here rather than trusted, carrying the
    hook's own pid-reuse guard: a recycled pid gets a new start time, so a
    recorded `lstart` that no longer matches means the process we were told about
    is gone and something unrelated now owns the number.
    """
    path = registry_path or SESSION_PIDS_PATH
    try:
        with open(path) as f:
            registry = json.load(f)
    except (OSError, json.JSONDecodeError, ValueError):
        return None
    entries = registry.get(session_id) if isinstance(registry, dict) else None
    if not isinstance(entries, list):
        return None
    for entry in reversed(entries):          # newest registration wins
        if not isinstance(entry, dict):
            continue
        pid = entry.get("pid")
        if not isinstance(pid, int):
            continue
        lstart = _pid_lstart(pid)
        if lstart is None:
            continue
        recorded = entry.get("lstart")
        if recorded and recorded != lstart:
            continue
        return entry
    return None


# ------------------------------------------------------------ the live terminal

def iterm_session_ids():
    """Every session id iTerm currently holds open, or None if it cannot answer.

    None is INDETERMINATE and must not be read as "that window is gone": iTerm not
    installed, AppleScript refused, automation permission missing, a timeout —
    none of those are evidence either way, and treating them as evidence would
    send a healthy in-place switch down the destructive resume path.
    """
    if not os.path.isdir("/Applications/iTerm.app"):
        return None
    script = ('tell application "iTerm" to get id of every session '
              'of every tab of every window')
    try:
        proc = subprocess.run(["osascript", "-e", script],
                              capture_output=True, text=True, timeout=30)
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    return {part.strip() for part in proc.stdout.split(",") if part.strip()}


def iterm_guid(entry):
    """The bare session GUID from a registry entry's captured ITERM_SESSION_ID.

    The variable's shape is "w3t0p0:GUID". The pane coordinates move when tabs are
    rearranged or windows merged; the GUID does not, so only the GUID is a stable
    handle on the window a session is actually sitting in.
    """
    raw = (entry or {}).get("iterm") or ""
    guid = raw.split(":")[-1].strip()
    return guid or None


# ---------------------------------------------------------------- accounts
#
# A model switch answers a MODEL-SCOPED limit (opus/sonnet/fable): another tier
# on the same account still has quota. It cannot answer a SHARED pool — the
# 5-hour and weekly limits gate every model the account can reach, so the only
# move left is another account, or waiting for the reset.
#
# The switch itself lives in the `claude_account` script beside this module; it
# owns the Keychain and ~/.claude.json handling. This section decides WHEN to
# call it and WHICH account to move to, and records what it learns so the next
# tick does not retry an account it already knows is spent.

ACCOUNT_TOOL = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "claude_account")
ACCOUNT_PREFERENCE = os.path.join(ROOT, "account-preference.json")
ACCOUNT_TIMEOUT = 20


def _account_run(args):
    """(ok, stdout, stderr) from the account tool. Never raises."""
    try:
        # Run through the tool's own shebang rather than naming an
        # interpreter: the supervisor is launched by launchd under the system
        # python, and hard-coding that here would break a machine where the
        # tool ships for a different one.
        proc = subprocess.run([ACCOUNT_TOOL] + list(args),
                              capture_output=True, text=True,
                              timeout=ACCOUNT_TIMEOUT)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, "", str(exc)
    return proc.returncode == 0, proc.stdout.strip(), proc.stderr.strip()


def account_preference():
    """Emails in the order the owner wants them used, best first.

    An explicit file wins. Without one the order is by plan size, because a 20x
    account carries four times the quota of a 5x and preferring it is not a
    matter of taste. Ordering is never inferred from which account happens to be
    logged in.
    """
    try:
        with open(ACCOUNT_PREFERENCE, encoding="utf-8") as fh:
            declared = json.load(fh)
        if isinstance(declared, list) and declared:
            return [str(e) for e in declared]
    except (OSError, ValueError):
        pass

    def plan_rank(record):
        tier = str(record.get("rate_limit_tier") or "")
        for size in (20, 5, 1):
            if f"max_{size}x" in tier:
                return -size
        return 0

    records = []
    store = os.path.join(ROOT, "accounts")
    try:
        names = sorted(os.listdir(store))
    except OSError:
        names = []
    for name in names:
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(store, name), encoding="utf-8") as fh:
                records.append(json.load(fh))
        except (OSError, ValueError):
            continue
    return [r["email"] for r in sorted(records, key=plan_rank)
            if r.get("email")]


def current_account():
    """The email logged in right now, or None if that cannot be read."""
    ok, out, _ = _account_run(["current"])
    return out.split()[0] if ok and out else None


def _account_record(email):
    """The stored record for `email`, or None when it cannot be read."""
    path = os.path.join(ROOT, "accounts", f"{email}.json")
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def account_is_open(email, kind):
    """Is `email` a usable destination for a session stalled on `kind`?

    Read from the stored record rather than by probing: a probe costs a request
    against an account we may not even switch to, and it can only be made after
    switching to it, which is the thing being decided.

    THE TWO SHARED POOLS ARE NOT INDEPENDENT. Both the 5-hour and the weekly
    limit mean "this account cannot serve a request right now" — they differ only
    in when they lift. So a weekly-spent account is closed to a session-limited
    move as well, and reading the pools separately would send a stalled session
    onto an account that cannot answer it either. Model-scoped pools
    (opus/sonnet/fable) genuinely are independent, but they never reach here:
    /model answers those without changing accounts.
    """
    record = _account_record(email)
    if record is None:
        return False, f"{email}: no stored record"

    usable, reason = _credential_reason(record)
    if not usable:
        return False, f"{email}: {reason}"

    now = time.time()
    for pool, entry in (record.get("limits") or {}).items():
        resets = entry.get("resets_at")
        if not isinstance(resets, (int, float)) or resets <= now:
            continue
        # A SHARED pool shuts the whole account. The 5-hour and weekly limits
        # gate every model, so an account spent on either cannot serve an Opus
        # request any more than a plain one — reading them as independent of the
        # model pools would send a session onto an account that answers nothing.
        # A MODEL pool is narrower: Opus being spent says nothing about Sonnet,
        # and nothing about the shared pools either.
        blocks = pool in SHARED_POOL_KINDS or pool == kind
        if blocks:
            when = datetime.datetime.fromtimestamp(resets, UTC)
            return False, (f"{email}: {pool} spent until "
                           f"{when:%Y-%m-%d %H:%M}Z")
    return True, f"{email}: {reason}"


def _credential_reason(record):
    """(usable, reason) for a stored record's refresh token.

    Mirrors the account tool's own check so the decision does not depend on
    parsing that tool's printed output.
    """
    oauth = (record.get("credentials") or {}).get("claudeAiOauth") or {}
    ms = oauth.get("refreshTokenExpiresAt")
    if not isinstance(ms, (int, float)) or ms <= 0:
        return True, "no refresh expiry recorded"
    when = datetime.datetime.fromtimestamp(ms / 1000, UTC)
    if when <= datetime.datetime.now(UTC):
        return False, f"refresh token expired {when:%Y-%m-%d %H:%M}Z"
    return True, f"credential ok to {when:%Y-%m-%d %H:%M}Z"


def choose_open_account(exhausted_kind, exclude=()):
    """(email, detail) for the best account to move to, or (None, why).

    Preference order decides, and the first account that is both credential-valid
    and not recorded as blocked on this pool wins.
    """
    tried = []
    for email in account_preference():
        if email in exclude:
            continue
        open_now, detail = account_is_open(email, exhausted_kind)
        tried.append(f"{email}={'open' if open_now else 'closed'}")
        if open_now:
            return email, detail
    if not tried:
        return None, ("no accounts captured — run "
                      "`.claude/scripts/claude_account capture` while logged "
                      "into each")
    return None, "every stored account is closed (" + ", ".join(tried) + ")"


def note_account_limit(email, kind, resets_at):
    """Record that `kind` is spent on `email` until `resets_at` (epoch seconds)."""
    if not (email and kind and resets_at):
        return False
    ok, _, _ = _account_run(["note-limit", email, kind, str(int(resets_at))])
    return ok


def switch_account(email, dry_run=False, force=False):
    """(ok, detail). Moves the machine's Claude Code login to `email`.

    `force` overrides the tool's refusal to switch while other sessions are
    running. That refusal is right for a person at a keyboard and wrong for a
    pool the whole account shares: see `account_switch_disrupts_others`.
    """
    args = ["switch", email]
    if dry_run:
        args.append("--dry-run")
    if force:
        args.append("--force")
    ok, out, err = _account_run(args)
    return ok, (out or err)


def live_sessions_count():
    """How many Claude Code sessions are running, excluding this process."""
    ok, out, _ = _account_run(["live-sessions"])
    try:
        return int(out.strip()) if ok else 0
    except ValueError:
        return 0


def account_switch_disrupts_others(kind):
    """Would switching accounts for `kind` harm sessions that are still working?

    A SHARED pool is shared by every session on the account, so when one dies on
    it the others are already dead or about to be: switching costs them nothing
    they had not already lost, and it is the only route back for any of them.

    A MODEL pool is not. A session stalled on Opus says nothing about a session
    happily running Fable, and moving the machine's account out from under that
    one breaks work that was fine — measured 2026-09-05, when an eight-second
    manual switch killed two subagents in another session.
    """
    return kind not in SHARED_POOL_KINDS


def refresh_account_capture():
    """Keep the ACTIVE account's stored blob current.

    Claude Code refreshes its own tokens on its own schedule. If a refresh also
    rotates the refresh token, a stored copy taken days ago is dead on arrival,
    and the failure appears as a relaunched session sitting at a login prompt.
    Re-capturing costs one Keychain read and one small file write, so the
    supervisor does it every tick rather than reasoning about whether rotation
    happens.
    """
    ok, _, _ = _account_run(["capture"])
    return ok
