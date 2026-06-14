#!/usr/bin/env bash
# prune_worktrees.sh — Remove specific worktrees by path or by sprint/iteration.
#
# IMPORTANT: This script changes to the MAIN project directory before removing
# worktrees. Running worktree removal from inside a worktree (or while an IDE has
# worktree files open) can crash the editor. This is the SANCTIONED way to remove
# worktrees — the guard-destructive-git.sh hook blocks ad-hoc `git worktree
# remove`/`prune` precisely so removal goes through this path.
#
# SAFETY: In --sprint mode, ONLY worktrees whose branch names match the ticket
# prefix for that sprint are removed. Worktrees from other sprints or active
# sessions are never touched.
#
# PREREQUISITE: developer agents must push their branches before reporting
# completion (enforced in agents/developer.md). Unpushed work in a worktree is
# lost when the worktree is removed — run harvest_unpushed_worktree_commits.sh
# first if a session was reaped.
#
# CONFIG: branch naming convention for --sprint mode. Override TICKET_PREFIX to
# match your project (default "bw-", so sprint 12 → branches "bw-12*").
TICKET_PREFIX="${TICKET_PREFIX:-bw-}"
#
# Usage:
#   prune_worktrees.sh --list                       # list all worktrees (no removal)
#   prune_worktrees.sh --sprint <N> --dry-run       # preview what would be removed
#   prune_worktrees.sh --sprint <N>                 # remove worktrees for sprint N
#   prune_worktrees.sh <worktree-path> [...]        # remove specific worktrees
#
# ALWAYS run --dry-run (or --list) first.

set -euo pipefail

# Resolve the main project directory (not a worktree). `git worktree list` always
# shows the main working tree first.
#
# Capture the full listing into a variable BEFORE slicing the first line. Piping
# `git worktree list --porcelain | head -1` closes the pipe after one line; with
# hundreds of worktrees git's output outruns the pipe buffer and the writer dies
# on SIGPIPE (exit 141), which `set -o pipefail` + `set -e` turn into a silent
# whole-script abort that removes nothing. Capturing first lets git finish
# writing; pure-bash parameter expansion then slices line 1 with no pipe at all.
_WT_PORCELAIN=$(git worktree list --porcelain 2>/dev/null)
_FIRST_LINE=${_WT_PORCELAIN%%$'\n'*}
MAIN_DIR=${_FIRST_LINE#worktree }

if [ -z "$MAIN_DIR" ]; then
  echo "Error: could not determine main project directory." >&2
  exit 1
fi

# Change to the main project directory before any worktree operations, so the
# shell (or an IDE terminal) is never inside a directory being removed.
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

  # Match worktrees whose branch contains this sprint's ticket prefix
  # (e.g. TICKET_PREFIX=bw-, sprint 12 → "bw-12").
  TICKET_PATTERN="${TICKET_PREFIX}${SPRINT}"

  if $DRY_RUN; then
    echo "DRY RUN — would remove these worktrees for sprint $SPRINT (pattern: $TICKET_PATTERN):"
  else
    echo "Removing worktrees for sprint $SPRINT (pattern: $TICKET_PATTERN)..."
  fi

  MATCHED=0
  REMOVED=0
  while IFS= read -r line; do
    WT_PATH=$(echo "$line" | awk '{print $1}')
    WT_BRANCH=$(echo "$line" | grep -o '\[.*\]' | tr -d '[]')

    # Never remove the main working tree.
    if [ "$WT_PATH" = "$MAIN_DIR" ]; then
      continue
    fi

    # Only this sprint's ticket branches (case-insensitive).
    if echo "$WT_BRANCH" | grep -qi "$TICKET_PATTERN"; then
      MATCHED=$((MATCHED + 1))
      if $DRY_RUN; then
        echo "  [would remove] $WT_PATH [$WT_BRANCH]"
      else
        echo "  Removing: $WT_PATH [$WT_BRANCH]"
        git worktree remove "$WT_PATH" --force 2>/dev/null || echo "    Warning: could not remove $WT_PATH"
        REMOVED=$((REMOVED + 1))
      fi
    fi
  done < <(git worktree list)

  if $DRY_RUN; then
    echo "Found $MATCHED worktree(s) matching sprint $SPRINT. Run without --dry-run to remove."
  else
    git worktree prune 2>/dev/null
    echo "Removed $REMOVED worktree(s) for sprint $SPRINT."
    echo ""
    echo "Remaining worktrees:"
    git worktree list
  fi
  exit 0
fi

# --- Mode: explicit paths ---
if [ $# -eq 0 ]; then
  echo "Usage: prune_worktrees.sh --list" >&2
  echo "       prune_worktrees.sh --sprint <N> [--dry-run]" >&2
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
