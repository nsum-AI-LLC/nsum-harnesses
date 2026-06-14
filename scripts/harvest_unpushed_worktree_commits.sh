#!/bin/bash
# harvest_unpushed_worktree_commits.sh — READ-ONLY scan for "stream-death" strands.
#
# A reaped session (the stream-death class: a tool result lands, the model stream
# then goes silent and is killed minutes later) can leave completed work that
# never reached git/origin. Two strand classes:
#
#   (a) SUBAGENT worktree commit committed-but-NEVER-pushed — a successful `git
#       commit` in a `.claude/worktrees/*` checkout whose paired `git push` was
#       never emitted. Recover by pushing the SHA to the PR branch:
#       `git push origin <sha>:refs/heads/<pr-branch>`.
#   (b) ORCHESTRATOR primary-tree planning artifact WRITTEN but never committed —
#       an untracked/modified `planning/**` file from an orphaned main-loop turn.
#       Reconcile (adopt-with-provenance, or discard) — NEVER silently inherit.
#
# This tool MUTATES NOTHING: no commit, no push, no checkout, and never
# `git worktree remove`/`prune`. A best-effort read-only `git fetch` keeps the
# origin refs current. Exit 0 always (it reports; it is not a gate).
#
# NOTE on squash-merge: once a PR squash-merges and its branch is deleted, the
# branch's original commits are reachable from NO origin ref, so they read as
# "unpushed" even though the work landed on the main branch as a squash. There is
# no reliable local content test for that. So this tool classifies by the one
# accurate signal — does the branch still exist on origin? — and defers the
# squash-vs-strand call to a cheap `gh pr list --state merged` check it prints.
# Scoping to the just-died worktree avoids the question entirely.
#
# Usage:
#   bash .claude/scripts/harvest_unpushed_worktree_commits.sh [--no-fetch] [<scope>]
#     <scope>   substring of a worktree dir name OR branch — the PRIMARY recovery
#               mode: when a dispatch dies, scope to THAT agent's worktree to see
#               its strand precisely, without the repo-wide stale-worktree noise.
#     (no scope) repo-wide sweep.
set -u

NO_FETCH=0
SCOPE=""
for arg in "$@"; do
  case "$arg" in
    --no-fetch) NO_FETCH=1 ;;
    *) SCOPE="$arg" ;;
  esac
done

ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null)}"
if [ -z "$ROOT" ] || [ ! -d "$ROOT/.git" ]; then
  echo "harvest: not a git repo (set CLAUDE_PROJECT_DIR or run inside the project)"
  exit 0
fi
WT_DIR="$ROOT/.claude/worktrees"

if [ "$NO_FETCH" -eq 0 ]; then
  git -C "$ROOT" fetch -q --prune origin 2>/dev/null || true
fi

found_strand=0      # genuine unrecovered work on a LIVE origin branch
found_unresolved=0  # branch not on origin — strand OR merged+deleted stale (verify)

echo "== (a) subagent worktree commits committed-but-unpushed (ahead of origin) =="
[ -n "$SCOPE" ] && echo "   (scoped to: *$SCOPE*)"
if [ -d "$WT_DIR" ]; then
  for wt in "$WT_DIR"/*/; do
    [ -d "$wt" ] || continue
    git -C "$wt" rev-parse --git-dir >/dev/null 2>&1 || continue
    branch=$(git -C "$wt" branch --show-current 2>/dev/null)
    name=$(basename "$wt")
    if [ -n "$SCOPE" ]; then
      case "$name$branch" in *"$SCOPE"*) : ;; *) continue ;; esac
    fi
    [ -z "$branch" ] && branch="(detached)"
    # Commits reachable from HEAD but on NO origin remote-tracking ref = not pushed.
    unpushed=$(git -C "$wt" rev-list HEAD --not --remotes=origin 2>/dev/null)
    [ -z "$unpushed" ] && continue
    n=$(printf '%s\n' "$unpushed" | grep -c .)
    if [ "$branch" != "(detached)" ] && \
       git -C "$wt" rev-parse --verify -q "refs/remotes/origin/$branch" >/dev/null 2>&1; then
      # The branch is LIVE on origin and HEAD is ahead of it → genuine unpushed work.
      found_strand=1
      echo "  [STRAND] $name  branch=$branch  ahead-by=$n — committed locally, NOT pushed to its live origin branch:"
      git -C "$wt" log --oneline --no-decorate HEAD --not --remotes=origin 2>/dev/null | sed 's/^/        /'
      echo "        recover: git -C \"$ROOT\" push origin <sha>:refs/heads/$branch"
    else
      # No origin/<branch>: an unpushed strand OR a merged+deleted stale worktree.
      found_unresolved=1
      echo "  [check] $name  branch=$branch  ahead-by=$n — branch not on origin: unpushed strand OR merged+deleted stale worktree."
      git -C "$wt" log --oneline --no-decorate HEAD --not --remotes=origin 2>/dev/null | sed 's/^/        /'
      echo "        verify: gh pr list --state merged --search \"$branch\"  → if merged: STALE (prune); if not: recover the SHA to the PR branch."
    fi
  done
else
  echo "  (no .claude/worktrees dir)"
fi

echo "== (b) primary-tree planning/** artifacts written-but-uncommitted =="
pb=$(git -C "$ROOT" status --porcelain -- planning/ 2>/dev/null)
if [ -n "$pb" ]; then
  found_strand=1
  printf '%s\n' "$pb" | while IFS= read -r line; do
    code=$(printf '%s' "$line" | cut -c1-2)
    path=$(printf '%s' "$line" | cut -c4-)
    case "$code" in
      "??") tag="UNTRACKED (orphaned write?) — reconcile: adopt-with-provenance or discard" ;;
      *)    tag="MODIFIED/STAGED — reconcile before a reset --hard loses it" ;;
    esac
    echo "  $code  $path"
    echo "        $tag"
  done
else
  echo "  (clean — no uncommitted planning/** artifacts)"
fi

echo "=="
if [ "$found_strand" -eq 0 ] && [ "$found_unresolved" -eq 0 ]; then
  echo "harvest: clean — no strands found."
else
  [ "$found_strand" -eq 1 ] && echo "harvest: genuine strand(s) above ([STRAND] / (b)) — reconcile with PROVENANCE (never silently inherit)."
  [ "$found_unresolved" -eq 1 ] && echo "harvest: [check] entries — run the printed gh check to tell a strand from a merged+deleted stale worktree."
  echo "         This tool reported only — it changed nothing."
fi
exit 0
