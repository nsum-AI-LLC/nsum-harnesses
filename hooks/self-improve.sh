#!/bin/bash
# Stop hook: reflect on the session transcript and propose harness improvements.
#
# The hook is non-blocking. It analyses the transcript for signals that the
# session learned something (user corrections, repeated mistakes, bypassed
# reminders) and writes a structured proposal to
# ~/.claude/{project_name}-proposals/ for the user to review later. The project
# name comes from the basename of $CLAUDE_PROJECT_DIR.
#
# Detection is intentionally conservative — false positives erode trust faster
# than missed lessons. The user reviews proposals with: claude_proposals

set -u

INPUT=$(cat)

# Extract transcript path and session id from hook input
TRANSCRIPT_PATH=$(echo "$INPUT" | jq -r '.transcript_path // empty' 2>/dev/null)
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // empty' 2>/dev/null)

# If we don't have a transcript path, exit silently — nothing to reflect on
if [ -z "$TRANSCRIPT_PATH" ] || [ ! -f "$TRANSCRIPT_PATH" ]; then
  exit 0
fi

REFLECTOR="$CLAUDE_PROJECT_DIR/.claude/scripts/reflect-on-transcript.py"

if [ ! -x "$REFLECTOR" ]; then
  exit 0
fi

# Run the reflector. Any output goes to stderr (visible in hook logs) but does
# not block the session. The reflector writes proposals to disk on its own.
# Pass project-dir so the proposals dir name is per-project, not hardcoded.
"$REFLECTOR" \
  --transcript "$TRANSCRIPT_PATH" \
  --session-id "${SESSION_ID:-unknown}" \
  --project-dir "$CLAUDE_PROJECT_DIR" \
  2>&1 || true

exit 0
