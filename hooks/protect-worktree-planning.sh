#!/usr/bin/env bash
# PreToolUse hook: prevent Write/Edit to planning/** that resolves INSIDE
# a git worktree.
#
# Planning artifacts (sprint plans, tickets, status updates, retrospectives,
# specs) are cross-cutting and reviewed on `main`. They must not be authored
# in a per-feature worktree where they'd be scoped to a branch the user
# doesn't routinely review and that gets discarded after merge.
#
# This hook blocks writes ONLY when the TARGET path resolves inside the
# current worktree (i.e., the worktree's own planning/ directory). Writes
# to absolute paths in the primary repo — e.g., from a worktree's CWD to
# /Users/.../proj/planning/foo — are ALLOWED. The orchestrator and
# subagents can write planning artifacts to the primary repo using its
# absolute path even when their CWD is in a worktree.
#
# Why we don't trust CLAUDE_PROJECT_DIR alone: in practice, Claude Code has
# been observed to set CLAUDE_PROJECT_DIR to the primary tree even when the
# subagent is running in a worktree. Favoring the (incorrect) env var over
# the real CWD caused this hook to no-op when it should have detected the
# worktree context. The fix uses git plumbing first (canonical), then $PWD,
# then $CLAUDE_PROJECT_DIR.
#
# It also compares the TARGET path against the worktree root rather than just
# checking CWD, and emits a syntactically valid suggested primary-repo path.
#
# See CLAUDE.md § "Worktree vs Primary Tree".
set -euo pipefail

# Determine the current shell's containing tree robustly. Prefer git plumbing
# (CWD-aware, ignores env-var drift), then $PWD, then $CLAUDE_PROJECT_DIR.
PROJECT_DIR="$(git rev-parse --show-toplevel 2>/dev/null || true)"
[ -z "${PROJECT_DIR}" ] && PROJECT_DIR="${PWD:-}"
[ -z "${PROJECT_DIR}" ] && PROJECT_DIR="${CLAUDE_PROJECT_DIR:-}"

# Only act when running inside a worktree under .claude/worktrees/.
if [[ "$PROJECT_DIR" != *"/.claude/worktrees/"* ]]; then
  exit 0
fi

# Extract the target file path. Write/Edit/MultiEdit all use tool_input.file_path.
FILE_PATH=$(jq -r '.tool_input.file_path // ""')
if [ -z "$FILE_PATH" ]; then
  exit 0
fi

# Normalize FILE_PATH to absolute. Relative paths resolve against the
# worktree's CWD; absolute paths stay as-is.
if [[ "$FILE_PATH" = /* ]]; then
  ABS_PATH="$FILE_PATH"
else
  ABS_PATH="$PROJECT_DIR/$FILE_PATH"
fi

# If the resolved target is NOT inside the worktree, allow the write.
# This is the key behavior change: primary-repo absolute paths from a
# worktree CWD are no longer blocked, even when they target planning/.
if [[ "$ABS_PATH" != "$PROJECT_DIR"/* ]]; then
  exit 0
fi

# Target is inside the worktree. Check whether it's a planning path.
REL_TO_WORKTREE="${ABS_PATH#$PROJECT_DIR/}"
case "$REL_TO_WORKTREE" in
  planning/*|*/planning/*) ;;
  *) exit 0 ;;
esac

# It's a worktree-internal planning write. Block it and emit the
# equivalent primary-repo path so the agent can redirect.
PRIMARY_BASE="${PROJECT_DIR%%/.claude/worktrees/*}"
PRIMARY_PATH="$PRIMARY_BASE/$REL_TO_WORKTREE"

REASON="Planning artifacts must be written to the primary repo, not a worktree. Write to: $PRIMARY_PATH (See CLAUDE.md § 'Worktree vs Primary Tree'.) The current path ($FILE_PATH) is inside a worktree branch that the user does not routinely review and that is discarded after merge."

jq -n --arg r "$REASON" '{decision: "block", reason: $r}'
exit 0
