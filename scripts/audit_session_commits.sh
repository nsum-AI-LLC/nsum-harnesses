#!/usr/bin/env bash
# audit_session_commits.sh — durable trace tool for "what did we commit
# vs what's in the primary working tree right now".
#
# Answers: "have any of my session's commits been undone by collisions,
# branch-thrash, or merge mishaps?"
#
# How: lists all commits on origin/main since the cutoff (default: 24h ago),
# then for each verifies it's reachable from origin/main HEAD. Also surfaces
# local working-tree modifications and untracked files — phantom changes that
# did NOT come from commits and may be cross-subagent contamination (a subagent
# writing to the primary tree via an absolute path).
#
# Assumes it lives at .claude/scripts/ (resolves the repo root as ../..).
#
# Usage:
#   audit_session_commits.sh                 # default: 24h cutoff
#   audit_session_commits.sh "2 hours ago"   # any git date spec
#   audit_session_commits.sh "2026-05-25 20:00"
#
# Exit codes:
#   0  origin/main has all expected commits; primary tree is clean
#   1  origin/main missing one or more expected commits (LOSS)
#   2  primary tree has phantom modifications (CONTAMINATION)
#   3  both (worst case)

set -u

CUTOFF="${1:-24 hours ago}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$REPO_ROOT" || { echo "Cannot cd to repo root: $REPO_ROOT" >&2; exit 99; }

# Pull latest origin/main so the audit reflects remote state.
git fetch origin main --quiet 2>/dev/null

echo "=== Session-commit audit ==="
echo "Repo:        $REPO_ROOT"
echo "Cutoff:      since '$CUTOFF'"
echo "origin/main: $(git rev-parse --short origin/main) — $(git log -1 --format=%s origin/main)"
echo ""

# Part 1: list commits on origin/main since cutoff
COMMITS=$(git log origin/main --since="$CUTOFF" --pretty=format:'%H')
COUNT=$(echo -n "$COMMITS" | grep -c '^' || true)
COUNT=${COUNT:-0}

echo "=== Commits on origin/main since cutoff ($COUNT) ==="
if [ "$COUNT" -eq 0 ]; then
  echo "  (none)"
else
  git log origin/main --since="$CUTOFF" --pretty=format:'  %h  %s' --abbrev-commit
  echo ""
fi
echo ""

# Part 2: verify each commit is reachable from origin/main HEAD
LOSS_COUNT=0
echo "=== Reachability check (each commit must be ancestor of origin/main HEAD) ==="
if [ "$COUNT" -eq 0 ]; then
  echo "  (no commits to check)"
else
  for sha in $COMMITS; do
    if git merge-base --is-ancestor "$sha" origin/main 2>/dev/null; then
      :  # reachable, no output
    else
      echo "  LOST: $sha is NOT reachable from origin/main HEAD"
      LOSS_COUNT=$((LOSS_COUNT + 1))
    fi
  done
  if [ "$LOSS_COUNT" -eq 0 ]; then
    echo "  All $COUNT commits reachable from origin/main HEAD."
  fi
fi
echo ""

# Part 3: working tree state (phantom modifications + untracked)
echo "=== Working tree state vs origin/main ==="
DIRTY=$(git status --short)
if [ -z "$DIRTY" ]; then
  echo "  Clean. No phantom modifications, no untracked files."
  TREE_STATUS=0
else
  MOD_COUNT=$(echo "$DIRTY" | grep -c '^ M\|^M\|^MM' || true)
  ADD_COUNT=$(echo "$DIRTY" | grep -c '^??' || true)
  DEL_COUNT=$(echo "$DIRTY" | grep -c '^ D\|^D' || true)
  MOD_COUNT=${MOD_COUNT:-0}; ADD_COUNT=${ADD_COUNT:-0}; DEL_COUNT=${DEL_COUNT:-0}
  echo "  Phantom modifications: $MOD_COUNT modified, $ADD_COUNT untracked, $DEL_COUNT deleted"
  echo ""
  echo "$DIRTY" | head -30
  if [ "$(echo "$DIRTY" | wc -l)" -gt 30 ]; then
    echo "  ... ($(echo "$DIRTY" | wc -l) total — only first 30 shown)"
  fi
  echo ""
  echo "  These are LOCAL changes not yet committed. If you didn't make them"
  echo "  yourself, they may be cross-subagent contamination (a subagent writing"
  echo "  to the primary tree via an absolute path)."
  echo "  Safe recovery: 'git reset --hard origin/main && git clean -fd'"
  echo "  WARNING: that wipes any uncommitted work. Verify first."
  TREE_STATUS=2
fi
echo ""

# Part 4: branch state
echo "=== Branch state ==="
CURRENT_BRANCH="$(git branch --show-current)"
echo "  Current branch: ${CURRENT_BRANCH:-<detached HEAD>}"
echo "  HEAD:           $(git rev-parse --short HEAD)"
echo "  origin/main:    $(git rev-parse --short origin/main)"
if [ "$(git rev-parse HEAD)" != "$(git rev-parse origin/main)" ]; then
  AHEAD=$(git rev-list --count origin/main..HEAD 2>/dev/null || echo "?")
  BEHIND=$(git rev-list --count HEAD..origin/main 2>/dev/null || echo "?")
  echo "  Divergence:     ahead $AHEAD, behind $BEHIND"
  if [ "$CURRENT_BRANCH" != "main" ] && [ -n "$CURRENT_BRANCH" ]; then
    echo "  NOTE: you are not on main. Local 'main' branch may be stale;"
    echo "        check with 'git log main..origin/main --oneline'."
  fi
fi
echo ""

# Part 5: summary verdict
echo "=== Verdict ==="
EXIT_CODE=0
if [ "$LOSS_COUNT" -gt 0 ]; then
  echo "  LOSS:           $LOSS_COUNT commits NOT on origin/main (lost work!)"
  EXIT_CODE=$((EXIT_CODE + 1))
fi
if [ "$TREE_STATUS" -eq 2 ]; then
  echo "  CONTAMINATION:  primary tree has uncommitted phantom changes"
  EXIT_CODE=$((EXIT_CODE + 2))
fi
if [ "$EXIT_CODE" -eq 0 ]; then
  echo "  CLEAN:          origin/main has all $COUNT session commits; primary tree clean."
fi

exit $EXIT_CODE
