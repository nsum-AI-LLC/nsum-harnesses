#!/usr/bin/env bash
# PreToolUse hook: block git push to branches with merged PRs.
# Reads Bash tool input from stdin, checks if the command is a git push,
# and if the current branch has a merged PR on GitHub.

set -euo pipefail

# Extract the command from stdin JSON
COMMAND=$(jq -r '.tool_input.command // ""')

# Only care about git push commands
if ! echo "$COMMAND" | grep -qE '^\s*git\s+push'; then
  exit 0
fi

# Get current branch
BRANCH=$(git -C "$CLAUDE_PROJECT_DIR" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
if [ -z "$BRANCH" ] || [ "$BRANCH" = "main" ] || [ "$BRANCH" = "master" ]; then
  exit 0
fi

# Detect the repo from git remote (works for any repo)
REPO=$(git -C "$CLAUDE_PROJECT_DIR" remote get-url origin 2>/dev/null | sed 's|.*github.com[:/]||; s|\.git$||')
if [ -z "$REPO" ]; then
  exit 0
fi

# Check if a merged PR exists for this branch
MERGED_PR=$(gh pr list --repo "$REPO" --head "$BRANCH" --state merged --json number,title --jq 'if length > 0 then .[0] | "#\(.number) \(.title)" else "" end' 2>/dev/null || echo "")

if [ -n "$MERGED_PR" ]; then
  echo "{\"decision\":\"block\",\"reason\":\"Branch '$BRANCH' has a merged PR ($MERGED_PR). Create a new branch instead of pushing to a merged PR's branch.\"}"
  exit 0
fi
