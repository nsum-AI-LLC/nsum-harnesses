#!/usr/bin/env bash
# PreToolUse hook scoped to subagents (via their YAML frontmatter's
# `hooks` field). Blocks Write/Edit/MultiEdit tool calls whose target
# resolves OUTSIDE the subagent's worktree.
#
# Root cause this hook addresses: subagents are spawned with
# `isolation: worktree`, giving them an isolated CWD and branch. But their
# Edit/Write tool calls can hard-code absolute paths to the primary repo
# (e.g., "/Users/.../<project>/src/foo.py"),
# bypassing the worktree isolation entirely. The orchestrator's primary
# tree then accumulates phantom modifications from N concurrent subagents,
# colliding with the orchestrator's own commits and corrupting the
# working-tree state mid-sprint.
#
# Detection / decision:
#
# 1. Determine the subagent's own worktree root robustly via git
#    plumbing (`git rev-parse --show-toplevel`), with $PWD and
#    $CLAUDE_PROJECT_DIR as fallbacks. If the subagent isn't in a
#    worktree (e.g., the hook fires from a non-worktree session by
#    accident), fail open — this hook is a subagent-scoped guard.
#
# 2. Resolve the target file path to absolute. Relative paths resolve
#    against the subagent's CWD.
#
# 3. If the target is INSIDE the subagent's worktree, allow.
#
# 4. If the target is in primary repo and is a planning file, allow.
#    Planning writes from worktree to primary are the one legitimate
#    cross-tree write — see `protect-worktree-planning.sh` for the
#    complementary rule that routes worktree-internal planning writes
#    BACK to primary. Together the two hooks form the planning-doc
#    routing contract.
#
# 5. Otherwise (target is primary repo non-planning, or target is
#    outside both trees) BLOCK with a clear redirect to the equivalent
#    in-worktree path.
#
# Wired via subagent YAML `hooks:` in your subagent definitions (e.g.
# agents/developer.md) so it applies ONLY to subagents, never to the
# orchestrator. The
# orchestrator works in the primary tree directly and must be free to
# write there; this hook would block it if applied at project level.
#
# Fail-open: any parse error allows the operation.

set -u

INPUT=$(cat)

# Extract target file path. Write/Edit/MultiEdit all use tool_input.file_path.
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // ""' 2>/dev/null)
if [ -z "$FILE_PATH" ]; then
  exit 0
fi

# Determine the subagent's own worktree root.
WORKTREE_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
[ -z "$WORKTREE_ROOT" ] && WORKTREE_ROOT="${PWD:-}"
[ -z "$WORKTREE_ROOT" ] && WORKTREE_ROOT="${CLAUDE_PROJECT_DIR:-}"
[ -z "$WORKTREE_ROOT" ] && exit 0  # can't determine — fail open

# This hook is meant for subagents in worktrees. If somehow it fires for
# a non-worktree session, fail open.
if [[ "$WORKTREE_ROOT" != *"/.claude/worktrees/"* ]]; then
  exit 0
fi

# Compute primary repo root (everything before /.claude/worktrees/...)
PRIMARY_ROOT="${WORKTREE_ROOT%%/.claude/worktrees/*}"

# Normalize target to absolute. Relative paths resolve against CWD,
# which for a subagent in its worktree is the worktree root.
if [[ "$FILE_PATH" = /* ]]; then
  ABS_PATH="$FILE_PATH"
else
  ABS_PATH="$WORKTREE_ROOT/$FILE_PATH"
fi

# Inside the subagent's worktree → allow (subagent doing its work).
if [[ "$ABS_PATH" == "$WORKTREE_ROOT"/* ]]; then
  exit 0
fi

# Outside the worktree. Check whether it's in primary repo.
if [[ "$ABS_PATH" != "$PRIMARY_ROOT"/* ]]; then
  # Outside both repos (e.g., /tmp scratch). Allow.
  exit 0
fi

# In primary repo. Allow planning paths (routed there by the
# complementary protect-worktree-planning.sh hook); block everything else.
REL_TO_PRIMARY="${ABS_PATH#$PRIMARY_ROOT/}"
case "$REL_TO_PRIMARY" in
  planning/*|*/planning/*)
    exit 0
    ;;
esac

# Non-planning primary write from a subagent worktree. This is the
# cross-subagent contamination class. Block with redirect.
WORKTREE_EQUIV="$WORKTREE_ROOT/$REL_TO_PRIMARY"
REASON="Subagent write to primary repo blocked. You are in worktree $WORKTREE_ROOT, but the target $ABS_PATH resolves to the orchestrator's primary repo at $PRIMARY_ROOT — only planning paths are routed to primary (handled by a separate hook). Write to your worktree instead: $WORKTREE_EQUIV — this is the cross-subagent contamination class that has corrupted the orchestrator's primary tree mid-sprint. See planning/PROCESS.md § 'Reviewing a PR' and .claude/agents/developer.md."

jq -n --arg r "$REASON" '{decision: "block", reason: $r}'
exit 0
