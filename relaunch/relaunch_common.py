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

# Kinds that gate EVERY model. Only these are worth waiting on; a model-scoped
# limit is escaped by switching tier, not by waiting.
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
