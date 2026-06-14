#!/bin/bash
# PostToolUse hook on Read: append the file path to this session's reads.jsonl.
# Fail-open: any error exits 0 silently. A broken tracker that blocks Reads is
# worse than missing read tracking.

set -u

INPUT=$(cat)

# Only fire on Read tool calls
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // empty' 2>/dev/null)
if [ "$TOOL_NAME" != "Read" ]; then
  exit 0
fi

FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty' 2>/dev/null)
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // empty' 2>/dev/null)

if [ -z "$FILE_PATH" ] || [ -z "$SESSION_ID" ]; then
  exit 0
fi

SCRIPT="$CLAUDE_PROJECT_DIR/.claude/scripts/precondition_state.py"
if [ ! -x "$SCRIPT" ]; then
  exit 0
fi

"$SCRIPT" record-read --session-id "$SESSION_ID" --path "$FILE_PATH" 2>/dev/null || true
exit 0
