#!/usr/bin/env bash
# PreToolUse hook on Bash: block destructive git commands that have a
# documented history of corrupting the orchestrator's primary tree or
# crashing VSCode. Applied project-wide; the orchestrator should never
# need these commands either (workspace cleanup goes through the
# dedicated script).
#
# Hard-blocks:
#   - `git worktree remove` (any variant, any path)
#   - `git worktree prune` (any variant)
#
# Per planning/PROCESS.md § "Worktree management": these commands crash
# VSCode and must be invoked only via .claude/scripts/prune_worktrees.sh,
# which the orchestrator runs at sprint close.
#
# Pass-through:
#   - `git worktree list` and other read-only worktree subcommands
#   - All other git commands
#
# Fail-open: any parse error allows the command.

set -u

INPUT=$(cat)

COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // ""' 2>/dev/null)
if [ -z "$COMMAND" ]; then
  exit 0
fi

# Match `git worktree remove` or `git worktree prune` only when it
# appears in COMMAND-INVOCATION position:
#   - start of command (^)
#   - after a shell separator: ; & | && || ` (
#   - after a newline
# Specifically NOT after a quote char (" or ') — that's string content,
# not a command invocation. This avoids false positives on commit
# messages, docstrings, and other string content that mentions the
# forbidden command as text.
#
# The allowed-preceding set captures the common invocation contexts:
#   git worktree remove ...        — ^ matches
#   cd /x && git worktree remove   — & matches (also && is &&)
#   git status; git worktree prune  — ; matches
#   $(git worktree remove ...)      — ( matches
#   `git worktree remove ...`       — ` matches
#   git status | git worktree remove — | matches (rare but possible)

if echo "$COMMAND" | grep -qE '(^|[[:space:];&|`(])git[[:space:]]+worktree[[:space:]]+(remove|prune)([[:space:]]|$)'; then
  REASON="git worktree remove/prune is forbidden — these commands crash VSCode and have a documented history of corrupting the orchestrator's primary tree by deleting another agent's locked worktree. Per planning/PROCESS.md § 'Worktree management', sprint-end worktree cleanup must go through .claude/scripts/prune_worktrees.sh which the orchestrator runs at sprint close. If you genuinely need to free a branch that's checked out in another worktree, push your changes from your own worktree via 'git push origin <local>:refs/heads/<remote>' refspec — it works whether or not another worktree has the branch checked out."
  jq -n --arg r "$REASON" '{decision: "block", reason: $r}'
  exit 0
fi

# All other commands pass through.
exit 0
