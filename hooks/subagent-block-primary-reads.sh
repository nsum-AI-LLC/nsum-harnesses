#!/usr/bin/env bash
# PreToolUse hook (subagent-scoped via agent YAML `hooks:`) on Read.
# Blocks a subagent running in a worktree from READING the orchestrator's PRIMARY
# checkout when a worktree-local twin of that file exists.
#
# This is the read-direction mirror of subagent-block-primary-writes.sh. Together
# they enforce one discipline: a subagent's code Reads/Edits/Writes all stay
# inside its own worktree. The /Users/.../<project>/... paths in CLAUDE.md, agent
# prompts, and the env header are the orchestrator's PRIMARY checkout — a
# DIFFERENT copy on a DIFFERENT branch.
#
# The failure this addresses: a subagent constructs an absolute path rooted at
# the project dir it knows ("/Users/.../<project>/src/foo") instead of its
# worktree ("/Users/.../<project>/.claude/worktrees/<id>/src/foo"). Writes to
# such paths are already blocked (subagent-block-primary-writes.sh + the
# platform's built-in shared-checkout Edit guard). But Reads were unguarded: the
# harness silently served the primary tree's (wrong-branch, stale) content. The
# agent then reasons against content that contradicts its own diff, concludes the
# tools are "buggy/caching", and burns a long, wrong debugging detour. This hook
# turns that silent stale read into one self-correcting BLOCK that names the exact
# worktree path to use instead.
#
# Decision logic (fail-open everywhere it cannot confirm a genuine violation):
#   1. Only act when OUR OWN tree is a worktree (subagent scope). If git/PWD can't
#      confirm a worktree root, fail open — never make a misbinding worse.
#   2. Resolve the target to absolute (relative paths resolve against the worktree
#      CWD and are always correct → allowed).
#   3. Inside our own worktree → allow (the normal case).
#   4. Inside ANOTHER worktree → defer to cross-worktree-read-guard.sh; ignore.
#   5. Outside the primary repo entirely (/tmp, ~/.claude, ...) → allow.
#   6. A primary-repo planning/** path → allow. Planning is the shared cross-tree
#      surface and lives canonically in primary (mirrors the write guards).
#   7. A primary-repo non-planning path WHERE a worktree twin exists → BLOCK with
#      a redirect to the worktree copy. No twin (a main-only file) → fail open, so
#      a main-only file is never a dead end.
#
# Wired via subagent YAML `hooks:` (developer / code-reviewer / system-analyst),
# NEVER at project level — the orchestrator reads the primary tree constantly and
# must never be blocked. (Belt-and-suspenders: step 1's worktree-scope guard
# already exits for the orchestrator even if mis-wired.)
#
# Fail-open: any parse error or unknown shape allows the read.

set -u

INPUT=$(cat)

FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // ""' 2>/dev/null)
if [ -z "$FILE_PATH" ]; then
  exit 0
fi

# Determine the subagent's own worktree root.
WORKTREE_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
[ -z "$WORKTREE_ROOT" ] && WORKTREE_ROOT="${PWD:-}"
[ -z "$WORKTREE_ROOT" ] && WORKTREE_ROOT="${CLAUDE_PROJECT_DIR:-}"
[ -z "$WORKTREE_ROOT" ] && exit 0  # can't determine — fail open

# Subagent scope: only act when our own tree is a worktree. Under env-drift where
# the root can't be confirmed as a worktree, this exits (fail open) not guesses.
if [[ "$WORKTREE_ROOT" != *"/.claude/worktrees/"* ]]; then
  exit 0
fi

# Primary repo root = everything before /.claude/worktrees/...
PRIMARY_ROOT="${WORKTREE_ROOT%%/.claude/worktrees/*}"

# Normalize target to absolute. Relative paths resolve against the worktree CWD,
# which is correct — they never trigger this guard.
if [[ "$FILE_PATH" = /* ]]; then
  ABS_PATH="$FILE_PATH"
else
  ABS_PATH="$WORKTREE_ROOT/$FILE_PATH"
fi

# Inside our own worktree → allow (normal subagent work).
if [[ "$ABS_PATH" == "$WORKTREE_ROOT"/* ]]; then
  exit 0
fi

# Inside ANOTHER worktree → cross-worktree-read-guard.sh owns this case.
if [[ "$ABS_PATH" == *"/.claude/worktrees/"* ]]; then
  exit 0
fi

# Outside the primary repo entirely (scratch, home dir, ...) → allow.
if [[ "$ABS_PATH" != "$PRIMARY_ROOT"/* ]]; then
  exit 0
fi

# Primary-repo path. Planning is the shared cross-tree surface (canonical in
# primary) — allow, mirroring the write guards.
REL_TO_PRIMARY="${ABS_PATH#$PRIMARY_ROOT/}"
case "$REL_TO_PRIMARY" in
  planning/*|*/planning/*)
    exit 0
    ;;
esac

# Non-planning primary read. Only block when a worktree twin exists — that is the
# divergence/confusion case. No twin → fail open (no dead-end).
WORKTREE_EQUIV="$WORKTREE_ROOT/$REL_TO_PRIMARY"
if [ ! -e "$WORKTREE_EQUIV" ]; then
  exit 0
fi

REASON="Subagent read of the orchestrator's PRIMARY checkout blocked. You are in worktree $WORKTREE_ROOT (your branch); $ABS_PATH points at the primary tree — a DIFFERENT copy on a DIFFERENT branch, so its contents are stale relative to your work and may include the orchestrator's uncommitted edits. Read your worktree's copy instead: $WORKTREE_EQUIV

Rule: every Read/Edit/Write path must begin with your worktree root ($WORKTREE_ROOT). The /Users/... project paths in CLAUDE.md, your agent prompt, and the env header are the orchestrator's primary checkout, not yours — translate them. (To inspect another branch's version of a file, use 'git show <ref>:$REL_TO_PRIMARY', not a primary-tree read. Planning docs under planning/** are the one exception — they live canonically in primary.)"

jq -n --arg r "$REASON" '{decision: "block", reason: $r}'
exit 0
