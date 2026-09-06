#!/usr/bin/env python3
"""Tests for multi-account rotation: pool scoping, burn attribution, selection.

Run: /usr/bin/python3 relaunch/test_accounts.py

These cover the decisions that are wrong in ways nothing else notices. Every
case here is one that shipped broken and was caught by measurement rather than
by reading the code, so each names the failure it prevents.

No network, no Keychain, no real accounts — the store is a temp directory and
the switch log is a list.
"""

import json
import os
import shutil
import sys
import tempfile
import time
import types

HERE = os.path.dirname(os.path.abspath(__file__))
FAILURES = []


def check(name, got, want):
    if got == want:
        print(f"  ok    {name}")
    else:
        print(f"  FAIL  {name}\n          got  {got!r}\n          want {want!r}")
        FAILURES.append(name)


def load(module_name, filename):
    """Import an extensionless CLI tool without running its __main__ guard."""
    path = os.path.join(HERE, filename)
    mod = types.ModuleType(module_name)
    mod.__dict__["__file__"] = path
    exec(compile(open(path).read(), path, "exec"), mod.__dict__)
    return mod


def test_pool_scoping(rc, store):
    """Which pools close an account for which need."""
    print("\npool scoping")
    future = time.time() + 3600

    def record(limits):
        path = os.path.join(store, "a@x.json")
        with open(path, "w") as fh:
            json.dump({"email": "a@x", "limits": limits,
                       "credentials": {"claudeAiOauth": {}}}, fh)

    # A shared pool gates every model, so it closes the account for everything.
    # Read as independent, it offered an exhausted account as a destination.
    for shared in ("session", "weekly", "credits"):
        record({shared: {"resets_at": future}})
        for need in ("session", "weekly", "opus", "sonnet", "credits"):
            check(f"{shared} spent -> closed for {need}",
                  rc.account_is_open("a@x", need)[0], False)

    # A model pool is narrower: Opus says nothing about Sonnet or the 5h pool.
    record({"opus": {"resets_at": future}})
    check("opus spent -> closed for opus", rc.account_is_open("a@x", "opus")[0], False)
    check("opus spent -> open for sonnet", rc.account_is_open("a@x", "sonnet")[0], True)
    check("opus spent -> open for session", rc.account_is_open("a@x", "session")[0], True)

    # An expired block is not a block.
    record({"weekly": {"resets_at": time.time() - 60}})
    check("expired block -> open", rc.account_is_open("a@x", "weekly")[0], True)


def test_credential_expiry(rc, store):
    """An expired refresh token is never a switch destination."""
    print("\ncredential expiry")
    path = os.path.join(store, "b@x.json")
    for label, ms, want in (
            ("expired refresh -> closed", (time.time() - 86400) * 1000, False),
            ("valid refresh   -> open", (time.time() + 86400) * 1000, True)):
        with open(path, "w") as fh:
            json.dump({"email": "b@x", "limits": {},
                       "credentials": {"claudeAiOauth": {
                           "refreshTokenExpiresAt": ms}}}, fh)
        check(label, rc.account_is_open("b@x", "session")[0], want)


def test_disruption_rule(rc):
    """Whether switching accounts harms sessions that are still working."""
    print("\ndisruption rule")
    for kind in ("session", "weekly", "credits"):
        check(f"{kind} shared -> switching harms nobody",
              rc.account_switch_disrupts_others(kind), False)
    for kind in ("opus", "sonnet", "fable"):
        check(f"{kind} model-scoped -> switching would harm others",
              rc.account_switch_disrupts_others(kind), True)


def test_burn_attribution(meter, tmp):
    """Burn belongs to the account that was live when it was spent.

    Summing the whole window billed a freshly-switched account for the previous
    one's usage: measured 72.3% against a server-reported 12%.
    """
    print("\nburn attribution")
    meter.SWITCH_LOG = os.path.join(tmp, "switches.jsonl")

    def switches(entries):
        with open(meter.SWITCH_LOG, "w") as fh:
            for entry in entries:
                fh.write(json.dumps(entry) + "\n")

    A, B = "a@x", "b@x"
    switches([])
    check("no log -> whole window", meter.active_intervals(A, 0, 100), [(0, 100)])

    switches([{"epoch": 40, "from": A, "to": B}])
    check("after a switch, incoming owns the tail",
          meter.active_intervals(B, 0, 100), [(40, 100)])
    check("after a switch, outgoing owns the head",
          meter.active_intervals(A, 0, 100), [(0, 40)])

    # Switching away and back inside one window: both spans belong to A.
    switches([{"epoch": 20, "from": A, "to": B},
              {"epoch": 70, "from": B, "to": A}])
    check("bounce -> two spans for A",
          meter.active_intervals(A, 0, 100), [(0, 20), (70, 100)])
    check("bounce -> one span for B",
          meter.active_intervals(B, 0, 100), [(20, 70)])

    switches([{"epoch": -50, "from": A, "to": B}])
    check("switch predates window -> all of it to B",
          meter.active_intervals(B, 0, 100), [(0, 100)])
    check("switch predates window -> none of it to A",
          meter.active_intervals(A, 0, 100), [])


def test_ceiling_is_per_account(meter, tmp):
    """The 5h ceiling is a property of the plan, not of the machine."""
    print("\nper-account ceiling")
    meter.ACCOUNTS_DIR = os.path.join(tmp, "accounts")
    os.makedirs(meter.ACCOUNTS_DIR, exist_ok=True)
    meter.FIRSTPARTY = os.path.join(tmp, "firstparty.json")
    with open(meter.FIRSTPARTY, "w") as fh:
        json.dump({"window_ceiling_tokens": 235_000_000}, fh)
    with open(os.path.join(meter.ACCOUNTS_DIR, "small@x.json"), "w") as fh:
        json.dump({"email": "small@x", "window_ceiling_tokens": 60_000_000}, fh)

    check("account with its own ceiling uses it",
          meter.ceiling("small@x"), (60_000_000.0, "account(small@x)"))
    check("account without one falls back",
          meter.ceiling("big@x"), (235_000_000.0, "firstparty"))


def main():
    tmp = tempfile.mkdtemp(prefix="relaunch-account-tests-")
    store = os.path.join(tmp, "accounts")
    os.makedirs(store)
    os.environ["CLAUDE_RELAUNCH_ROOT"] = tmp
    try:
        sys.path.insert(0, HERE)
        import relaunch_common as rc
        rc.ACCOUNTS_DIR = store
        # account_is_open reads the store directly; point it at the fixture.
        rc._account_record = lambda email: _read(store, email)
        meter = load("meter_under_test", "claude_usage_meter")

        test_pool_scoping(rc, store)
        test_credential_expiry(rc, store)
        test_disruption_rule(rc)
        test_burn_attribution(meter, tmp)
        test_ceiling_is_per_account(meter, tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {', '.join(FAILURES)}")
        return 1
    print("all passed")
    return 0


def _read(store, email):
    try:
        with open(os.path.join(store, f"{email}.json")) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


if __name__ == "__main__":
    sys.exit(main())
