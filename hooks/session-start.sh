#!/usr/bin/env bash
# SessionStart hook: print the project briefing as session-start context.
#
# This is the generic version: it just invokes the briefing generator. Projects
# that need setup at session start (activating a virtualenv/conda env, sourcing
# nvm, exporting credentials) should add those steps ABOVE the briefing call in
# their own copy.
#
# Fail-soft: never block session start. Any error is swallowed.
set -u

SCRIPT_DIR="${CLAUDE_PROJECT_DIR:-$PWD}/.claude/scripts"
BRIEFING="$SCRIPT_DIR/session_briefing.py"

if [ -f "$BRIEFING" ] && command -v python3 >/dev/null 2>&1; then
  python3 "$BRIEFING" 2>/dev/null || true
fi

exit 0
