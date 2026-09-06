#!/bin/bash
# Session-continuity supervisor — installer.
#
# Installs the supervisor + spec writer + usage meter into the relaunch root,
# arms the launchd tick, and proves the pipeline with a self-test and a dry run.
#
# Root resolution (same order the code uses): $CLAUDE_RELAUNCH_ROOT, then an
# EXISTING ~/.claude/willcall-relaunch (so an older install keeps its specs,
# log and history in place), then ~/.claude/claude-relaunch.
set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)"

if [ -n "${CLAUDE_RELAUNCH_ROOT:-}" ]; then
  ROOT="$CLAUDE_RELAUNCH_ROOT"
elif [ -d "$HOME/.claude/willcall-relaunch" ]; then
  ROOT="$HOME/.claude/willcall-relaunch"
  echo "== upgrading the existing install at $ROOT =="
else
  ROOT="$HOME/.claude/claude-relaunch"
fi
BIN="$ROOT/bin"
# Reuse an existing job's label rather than adding a second one. A machine
# upgraded from the original install already has ai.willcall.* loaded; writing a
# new label would leave TWO supervisors ticking the same spec directory, which
# races on consuming a spec and can double-launch a session.
LEGACY_PLIST="$HOME/Library/LaunchAgents/ai.willcall.relaunch-supervisor.plist"
if [ -f "$LEGACY_PLIST" ]; then
  PLIST_DST="$LEGACY_PLIST"
  PLIST_LABEL="ai.willcall.relaunch-supervisor"
  echo "== reusing the existing launchd label ($PLIST_LABEL) =="
else
  PLIST_DST="$HOME/Library/LaunchAgents/ai.claude.relaunch-supervisor.plist"
  PLIST_LABEL="ai.claude.relaunch-supervisor"
fi

mkdir -p "$BIN" "$ROOT/specs" "$ROOT/done"
# Stored account credentials. 0700 because the files inside hold OAuth tokens;
# they are written 0600 by the tool itself.
mkdir -p "$ROOT/accounts" && chmod 700 "$ROOT/accounts"

install -m 0755 "$SRC/claude_relaunch_supervisor" "$BIN/claude_relaunch_supervisor"
install -m 0755 "$SRC/claude_write_relaunch_spec" "$BIN/claude_write_relaunch_spec"
install -m 0755 "$SRC/claude_usage_meter"         "$BIN/claude_usage_meter"
# Multi-account rotation. The supervisor shells out to this rather than
# importing it, so it has to be executable and beside the others.
install -m 0755 "$SRC/claude_account"             "$BIN/claude_account"
# Shared library — the supervisor and the spec writer both import it, so
# omitting it leaves an install that cannot even start.
install -m 0755 "$SRC/relaunch_common.py"         "$BIN/relaunch_common.py"

echo "== self-test: death detection, relaunch mode, and the no-model rule =="
/usr/bin/python3 - "$BIN/claude_relaunch_supervisor" <<'PYEOF'
import importlib.util, sys, time
from importlib.machinery import SourceFileLoader
# The file is extensionless (a CLI tool), so name the source loader explicitly —
# spec_from_file_location picks a loader by extension and returns none here.
loader = SourceFileLoader("sup", sys.argv[1])
spec = importlib.util.spec_from_loader("sup", loader)
m = importlib.util.module_from_spec(spec); loader.exec_module(m)

# the REAL main-session death shape (measured 2026-07-03 record)
pos = '{"type":"assistant","isApiErrorMessage":true,"message":{"content":[{"type":"text","text":"You’ve hit your session limit · resets 3:20am (America/Los_Angeles)"}]}}'
rec = m.terminal_limit_record("x\n" + pos + "\n")
assert rec, "FAIL: real death record not detected"
assert m.rc.parse_reset(rec, time.time()), "FAIL: reset time not parsed"

# negative control: QUOTED 429 text in a non-error record (the false-positive
# class measured on the 2026-08-30 orchestrator transcript)
neg = '{"type":"assistant","message":{"content":[{"type":"text","text":"agent died: error type rate_limit, HTTP 429, resets 4am (America/Los_Angeles)"}]}}'
assert m.terminal_limit_record("x\n" + neg + "\n") is None, \
    "FAIL: false positive on quoted 429 text"

# A usage-limit death must RESUME the same session, not start a fresh one on
# /pickup — a killed session wrote no handoff for a fresh session to read.
watchdog = {"session_id": "s", "created_by": "watchdog", "reason": "usage-crash-watchdog"}
assert m.relaunch_mode(watchdog) == "resume", "FAIL: usage death does not resume"
cmd, mode = m.build_command(watchdog, "/tmp")
assert mode == "resume" and "/pickup" not in cmd, "FAIL: usage death builds a pickup"
assert "--model" not in cmd, "FAIL: relaunch pins a model (settings owns the tier)"
assert m.relaunch_mode({"created_by": "wind-down", "reason": "context"}) == "pickup", \
    "FAIL: context wind-down should still pick up"

# The project resolver must handle a dash inside a real path segment.
import os, tempfile
d = tempfile.mkdtemp(); nested = os.path.join(d, "my-project", ".claude")
os.makedirs(nested)
assert m.rc.resolve_project_slug(nested.replace("/", "-")) == nested, \
    "FAIL: slug resolution mishandles dashes/dot-dirs"
print("self-test PASS: death detected; quoted 429 ignored; usage death resumes; "
      "context wind-down picks up; no model pinned; slugs resolve")
PYEOF

cat > "$PLIST_DST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$PLIST_LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>$BIN/claude_relaunch_supervisor</string>
  </array>
  <key>StartInterval</key><integer>120</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>$ROOT/supervisor-stdout.log</string>
  <key>StandardErrorPath</key><string>$ROOT/supervisor-stderr.log</string>
</dict>
</plist>
PLIST

# Re-arm cleanly whether or not a prior version was loaded.
launchctl unload "$PLIST_DST" 2>/dev/null || true
launchctl load "$PLIST_DST"

echo "== armed. launchd tick every 120s. root: $ROOT =="
echo "== kill switch: touch $ROOT/pause   (rm to resume) =="
echo "== unload:      launchctl unload $PLIST_DST =="
echo
echo "== NOTE: the retire-on-resume half is a SessionStart hook. Wire it per project:"
echo "     cp hooks/session-pid-registry.py <project>/.claude/hooks/"
echo "   then add it to SessionStart in that project's .claude/settings.json."
echo
echo
echo "== multi-account rotation (optional) =="
echo "   Two accounts let a session that hits a 5-hour, weekly or spend limit"
echo "   carry on instead of waiting for the reset. To set it up:"
echo "     $BIN/claude_account setup"
echo "   It reports what is saved and names the next step each time you run it."
echo
echo "== dry-run tick (decisions only): =="
/usr/bin/python3 "$BIN/claude_relaunch_supervisor" --dry-run
echo "== log tail: =="
tail -5 "$ROOT/log.jsonl" 2>/dev/null || echo "(no log yet)"
