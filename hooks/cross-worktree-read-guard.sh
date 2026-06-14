#!/bin/bash
# PreToolUse hook on Read: block reads of files in a worktree the current
# session does NOT own.
#
# The wrong-tree-read bug: the orchestrator (in the primary tree) accidentally
# reads /Users/.../proj/.claude/worktrees/branch-X/src/foo.py when it meant
# the primary tree's /Users/.../proj/src/foo.py. The orchestrator then makes
# decisions on stale code from a different branch.
#
# Detection: if the target path matches `.../.claude/worktrees/SOMETHING/...`
# AND the current shell is NOT inside that same worktree, block the read.
# Sessions running INSIDE a worktree (e.g., developer subagents) are unaffected
# — they read files within their own worktree freely.
#
# Why we don't trust CLAUDE_PROJECT_DIR alone: in practice, Claude Code has
# been observed to set CLAUDE_PROJECT_DIR to the primary tree even when the
# subagent is running in a worktree. Trusting it caused this hook to
# block legitimate own-worktree reads. The fix uses
# `git rev-parse --show-toplevel` (canonical, CWD-aware, ignores environment-
# variable drift) with $PWD and CLAUDE_PROJECT_DIR as fallbacks. We also keep
# CLAUDE_PROJECT_DIR as a belt-and-suspenders OK signal: if EITHER git/PWD
# or CPD says "we own this worktree," allow the read.
#
# Fail-open: any parse error allows the read.

set -u

INPUT=$(cat)

TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // empty' 2>/dev/null)
if [ "$TOOL_NAME" != "Read" ]; then
  exit 0
fi

FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty' 2>/dev/null)
if [ -z "$FILE_PATH" ]; then
  exit 0
fi

# Detect "is this path inside a worktree?" Pattern: */.claude/worktrees/NAME/...
if ! echo "$FILE_PATH" | grep -qE '/\.claude/worktrees/[^/]+/'; then
  exit 0  # not a worktree path, allow
fi

# Extract the worktree-root prefix (everything up to and including the first
# segment after `.claude/worktrees/`)
TARGET_WT_ROOT=$(echo "$FILE_PATH" | sed -E 's|^(.*/\.claude/worktrees/[^/]+)/.*|\1|')

# Determine the current shell's containing tree robustly. Prefer git plumbing
# (canonical, follows the actual CWD), then $PWD, then $CLAUDE_PROJECT_DIR.
CURRENT_TREE="$(git rev-parse --show-toplevel 2>/dev/null || true)"
[ -z "$CURRENT_TREE" ] && CURRENT_TREE="${PWD:-}"
[ -z "$CURRENT_TREE" ] && CURRENT_TREE="${CLAUDE_PROJECT_DIR:-}"

# If the current tree (per git/PWD) is inside the target worktree, allow.
case "$CURRENT_TREE" in
  "$TARGET_WT_ROOT"|"$TARGET_WT_ROOT"/*)
    exit 0
    ;;
esac

# Belt-and-suspenders: if CLAUDE_PROJECT_DIR independently says we own the
# target worktree (and disagrees with git/PWD), allow. Handles edge cases
# where git/PWD don't reflect reality (e.g., hook invoked from a temp CWD
# outside the repo). Also future-proofs against a harness fix that starts
# setting CLAUDE_PROJECT_DIR correctly in worktree subagents.
if [ -n "${CLAUDE_PROJECT_DIR:-}" ] && [ "${CLAUDE_PROJECT_DIR:-}" != "${CURRENT_TREE:-}" ]; then
  case "$CLAUDE_PROJECT_DIR" in
    "$TARGET_WT_ROOT"|"$TARGET_WT_ROOT"/*)
      exit 0
      ;;
  esac
fi

# Otherwise: cross-worktree read. Block with a clear message including both
# signals so the user can debug environment drift.
echo "CROSS-WORKTREE READ BLOCKED" >&2
echo "" >&2
echo "  Target path is inside a worktree:" >&2
echo "    $TARGET_WT_ROOT" >&2
echo "  Current shell's containing tree (per git/PWD):" >&2
echo "    ${CURRENT_TREE:-<unset>}" >&2
echo "  CLAUDE_PROJECT_DIR:" >&2
echo "    ${CLAUDE_PROJECT_DIR:-<unset>}" >&2
echo "" >&2
echo "  If you meant to read the primary tree's version, drop the worktree" >&2
echo "  prefix. If you genuinely need to read another worktree's file (rare):" >&2
echo "  cd into that worktree first, or open a separate Claude session there." >&2
exit 2
