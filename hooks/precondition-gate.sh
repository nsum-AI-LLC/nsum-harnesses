#!/bin/bash
# PreToolUse hook: block action tools (Edit|Write|Skill|Agent) when required
# reads have not been completed this session.
#
# Fail-open: any error in the gate exits 0 (allow the tool call). A broken gate
# that blocks every tool call is worse than no gate.
#
# To skip gating for a specific tool, adjust the matcher in settings.json.
# Read is NEVER gated (otherwise: deadlock — model can't satisfy preconditions).

set -u

INPUT=$(cat)

TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // empty' 2>/dev/null)
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // empty' 2>/dev/null)

# Never gate Read
if [ "$TOOL_NAME" = "Read" ]; then
  exit 0
fi

if [ -z "$SESSION_ID" ]; then
  exit 0
fi

SCRIPT="$CLAUDE_PROJECT_DIR/.claude/scripts/precondition_state.py"
if [ ! -x "$SCRIPT" ]; then
  exit 0
fi

# Exit code 2 from `check` → block; the script writes a clear message to stderr
# that the model sees when blocked.
"$SCRIPT" check --session-id "$SESSION_ID" --project-dir "$CLAUDE_PROJECT_DIR"
RC=$?

# Any non-2 exit (0 = no preconditions, other = script error) is allow.
if [ "$RC" = "2" ]; then
  exit 2
fi

exit 0
