#!/usr/bin/env bash
# prune_worktrees.sh — Remove specific worktrees by path or sprint.
#
# IMPORTANT: This script changes to the MAIN project directory before
# removing worktrees. Running worktree removal from inside a worktree
# (or while the IDE has worktree files open) crashes VSCode.
#
# SAFETY: In --sprint mode, ONLY worktrees whose branch names match that
# sprint's ticket pattern (bw-{N}*) are removed. Worktrees from other
# sprints or active development sessions are never touched.
#
# PREREQUISITE: Developer agents must push their branches before reporting
# completion (enforced in .claude/agents/developer.md). Unpushed work in a
# worktree is lost when the worktree is removed.
#
# Usage:
#   prune_worktrees.sh --list                       # list all worktrees (no removal)
#   prune_worktrees.sh --sprint <N> --dry-run       # preview what would be removed
#   prune_worktrees.sh --sprint <N>                 # remove worktrees for sprint N
#   prune_worktrees.sh --stale --dry-run            # preview state-based cleanup
#   prune_worktrees.sh --stale                      # remove every SAFE worktree
#   prune_worktrees.sh <worktree-path> [...]        # remove specific worktrees
#
# PREFER --stale for routine cleanup. --sprint keys on BRANCH NAMES (bw-{N}*),
# which the platform's agent-<hash> detached-HEAD worktrees never match: at 341
# worktrees, 70% were invisible to it and it reported "0 matched" rather than
# erroring. --stale keys on STATE (pushed + clean + idle) and cannot go blind
# the same way.
#
# Examples:
#   prune_worktrees.sh --sprint 28 --dry-run
#   prune_worktrees.sh --sprint 28
#   prune_worktrees.sh /Users/leo/projects/willcall/.claude/worktrees/agent-a1b2c3d4

set -euo pipefail

# Resolve the main project directory (not a worktree).
# git worktree list always shows the main working tree first.
#
# Capture the full listing into a variable BEFORE slicing the first line.
# Piping `git worktree list --porcelain | head -1` closes the pipe after one
# line; with hundreds of worktrees git's output outruns the pipe buffer and the
# writer dies on SIGPIPE (exit 141), which `set -o pipefail` + `set -e` turn
# into a silent whole-script abort (it removed nothing). Capturing first lets
# git finish writing; pure-bash parameter expansion then slices line 1 with no
# pipe at all, so SIGPIPE is structurally impossible regardless of worktree count.
_WT_PORCELAIN=$(git worktree list --porcelain 2>/dev/null)
_FIRST_LINE=${_WT_PORCELAIN%%$'\n'*}
MAIN_DIR=${_FIRST_LINE#worktree }

if [ -z "$MAIN_DIR" ]; then
  echo "Error: could not determine main project directory." >&2
  exit 1
fi

# Change to the main project directory before any worktree operations.
# This prevents IDE crashes caused by removing the directory the shell
# (or an IDE terminal) is currently inside.
cd "$MAIN_DIR"

# --- Mode: list ---
if [ "${1:-}" = "--list" ]; then
  echo "Worktrees (from $MAIN_DIR):"
  git worktree list
  exit 0
fi

# --- Mode: sprint ---
if [ "${1:-}" = "--sprint" ]; then
  SPRINT="${2:-}"
  if [ -z "$SPRINT" ]; then
    echo "Usage: prune_worktrees.sh --sprint <N> [--dry-run]" >&2
    exit 1
  fi

  DRY_RUN=false
  if [ "${3:-}" = "--dry-run" ]; then
    DRY_RUN=true
  fi

  # Match worktrees whose branch contains this sprint's ticket prefix.
  # Sprint 28 tickets are BW-28xx, so branches are bw-28*.
  # Also matches helper branches: batch1-merge, batch2-merge that were
  # created as merge bases during the sprint.
  TICKET_PATTERN="bw-${SPRINT}"

  if $DRY_RUN; then
    echo "DRY RUN — would remove these worktrees for sprint $SPRINT:"
  else
    echo "Removing worktrees for sprint $SPRINT..."
  fi

  MATCHED=0
  REMOVED=0
  while IFS= read -r line; do
    WT_PATH=$(echo "$line" | awk '{print $1}')
    # Detached-HEAD worktrees have no [branch] bracket — grep -o legitimately
    # finds no match there. Under `set -o pipefail`, an unguarded failure here
    # aborts the whole script silently (mid-loop, no error message), which is
    # exactly what happened before this fix: every sprint's dry-run reported
    # zero matches because the loop died on the first detached-HEAD entry.
    WT_BRANCH=$(echo "$line" | grep -o '\[.*\]' | tr -d '[]' || true)

    # Skip the main working tree — never remove it
    if [ "$WT_PATH" = "$MAIN_DIR" ]; then
      continue
    fi

    # Only match this sprint's ticket branches (case-insensitive)
    if echo "$WT_BRANCH" | grep -qi "$TICKET_PATTERN"; then
      MATCHED=$((MATCHED + 1))
      if $DRY_RUN; then
        echo "  [would remove] $WT_PATH [$WT_BRANCH]"
      else
        # Preserve session logs before removing the worktree.
        # Archive to ~/.claude/session-archive/ (central, survives pruning).
        WT_ENCODED=$(echo "$WT_PATH" | sed 's|/|-|g')
        WT_SESSION_DIR="$HOME/.claude/projects/$WT_ENCODED"
        ARCHIVE_DIR="$HOME/.claude/session-archive"
        if [ -d "$WT_SESSION_DIR" ]; then
          mkdir -p "$ARCHIVE_DIR"
          for f in "$WT_SESSION_DIR"/*.jsonl; do
            [ -f "$f" ] || continue
            BASENAME=$(basename "$f")
            cp "$f" "$ARCHIVE_DIR/$BASENAME"
            echo "    Archived session: $BASENAME"
          done
        fi
        echo "  Removing: $WT_PATH [$WT_BRANCH]"
        git worktree remove "$WT_PATH" --force 2>/dev/null || echo "    Warning: could not remove $WT_PATH"
        REMOVED=$((REMOVED + 1))
      fi
    fi
  done < <(git worktree list)

  if $DRY_RUN; then
    echo "Found $MATCHED worktree(s) matching sprint $SPRINT. Run without --dry-run to remove."
  else
    # Prune stale references (worktrees whose directories were deleted manually)
    git worktree prune 2>/dev/null
    echo "Removed $REMOVED worktree(s) for sprint $SPRINT."
    echo ""
    echo "Remaining worktrees:"
    git worktree list
  fi
  exit 0
fi

# --- Mode: stale (branch-name-independent) ---
#
# Why this exists: --sprint N matches worktrees whose BRANCH NAME contains bw-N,
# but the platform creates agent worktrees as agent-<hash> with a DETACHED HEAD.
# Measured 2026-09-04 at 341 worktrees: 238 (70%) had no matchable branch at all,
# and the sprint mode reports "0 matched" rather than erroring — so every sprint
# close looked clean while reclaiming nothing. This mode keys on STATE instead of
# naming, so it cannot go blind the same way.
#
# It prunes ONLY what classify_worktrees.py calls SAFE: every commit already on a
# remote, nothing uncommitted, nothing untracked, and idle. REVIEW (the BW-5055
# residue class, which can hold staged REVERTS that read as unharvested work),
# UNKNOWN and HOLD are never touched by this mode.
if [ "${1:-}" = "--stale" ]; then
  CLASSIFIER="$MAIN_DIR/.claude/scripts/classify_worktrees.py"
  if [ ! -x "$CLASSIFIER" ]; then
    echo "Error: $CLASSIFIER not found or not executable." >&2
    exit 1
  fi

  SAFE_LIST=$("$CLASSIFIER" --print-safe)
  if [ -z "$SAFE_LIST" ]; then
    echo "No SAFE worktrees to prune."
    "$CLASSIFIER" | head -8
    exit 0
  fi

  SAFE_COUNT=$(printf '%s\n' "$SAFE_LIST" | wc -l | tr -d ' ')
  if [ "${2:-}" = "--dry-run" ]; then
    echo "DRY RUN — would remove $SAFE_COUNT SAFE worktree(s):"
    printf '  [would remove] %s\n' $SAFE_LIST
    exit 0
  fi

  echo "Removing $SAFE_COUNT SAFE worktree(s)..."
  REMOVED=0
  for WT_PATH in $SAFE_LIST; do
    if [ -d "$WT_PATH" ]; then
      echo "Removing: $WT_PATH"
      git worktree remove "$WT_PATH" --force 2>/dev/null \
        || echo "  Warning: could not remove $WT_PATH"
      REMOVED=$((REMOVED + 1))
    fi
  done
  git worktree prune 2>/dev/null
  echo "Removed $REMOVED worktree(s)."
  echo
  echo "What remains (nothing below is auto-pruned):"
  "$CLASSIFIER" | sed -n '3,9p'
  exit 0
fi

# --- Mode: explicit paths ---
if [ $# -eq 0 ]; then
  echo "Usage: prune_worktrees.sh --list" >&2
  echo "       prune_worktrees.sh --sprint <N> [--dry-run]" >&2
  echo "       prune_worktrees.sh --stale [--dry-run]" >&2
  echo "       prune_worktrees.sh <worktree-path> [...]" >&2
  exit 1
fi

REMOVED=0
for WT_PATH in "$@"; do
  if [ -d "$WT_PATH" ]; then
    echo "Removing: $WT_PATH"
    git worktree remove "$WT_PATH" --force 2>/dev/null || echo "  Warning: could not remove $WT_PATH"
    REMOVED=$((REMOVED + 1))
  else
    echo "Skipping (not found): $WT_PATH"
  fi
done

git worktree prune 2>/dev/null
echo "Removed $REMOVED worktree(s)."
