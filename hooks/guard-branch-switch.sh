#!/usr/bin/env bash
# PreToolUse hook on Bash: block branch-switching git/gh commands that run
# in the PRIMARY repo CWD, where they thrash the shared branch state.
#
# Root cause this hook addresses (the cross-subagent branch-switch collision):
# git branch refs are SHARED across all worktrees of a repo (only HEAD and the
# working tree are per-worktree). A subagent that ends up running in the
# orchestrator's PRIMARY cwd (isolation can fail) and runs
#   git checkout <ref> | git switch <ref> | gh pr checkout <N>
# moves the primary tree's HEAD off `main`, detaches it, and can lock `main`
# in another worktree — corrupting the orchestrator's branch state mid-sprint.
# The existing guards block primary WRITES (subagent-block-primary-writes.sh)
# and destructive worktree commands (guard-destructive-git.sh) but NOT branch
# switches. This closes that gap.
#
# Decision matrix:
#   - command is not a branch switch              -> ALLOW
#   - command is a working-tree file restore       -> ALLOW
#       (`git checkout -- <path>`, `git checkout .`, `git checkout <ref> -- <path>`)
#   - cwd git toplevel is a worktree               -> ALLOW
#       (a subagent switching branches IN ITS OWN worktree is isolated and fine;
#        code-reviewers legitimately `gh pr checkout` inside their worktree)
#   - cwd git toplevel is PRIMARY, escape hatch set -> ALLOW
#       (CLAUDE_ALLOW_CHECKOUT=1 — orchestrator recovery, deliberate single command)
#   - cwd git toplevel is PRIMARY, no escape hatch  -> BLOCK
#   - cwd not in a git repo                         -> ALLOW (fail open)
#
# Fail-open on any parse/dependency error.

set -u

INPUT=$(cat)

COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // ""' 2>/dev/null)
[ -z "$COMMAND" ] && exit 0

# --- 1. Is this a branch-switching command at COMMAND START? ---
# We match the branch-switch keyword ONLY at the very start of the command
# (optional leading whitespace). Rationale:
#
#   * The only dangerous case this CWD-based guard can RELIABLY detect is a
#     mislocated subagent whose cwd is ALREADY the primary repo running a
#     top-level `git checkout <ref>` — exactly the observed incident. A
#     `cd /primary && git checkout ...` cannot be caught regardless, because
#     the hook reads cwd BEFORE the inline `cd` runs (cwd is still the
#     worktree at hook time → allowed). So matching mid-command separators
#     buys no real safety.
#   * Matching only at `^` eliminates the dominant false-positive class:
#     commit messages (heredocs), echo strings, test data, and docs that
#     mention `git checkout` / `gh pr checkout` as TEXT. Those would block
#     legitimate commits constantly.
#
# grep -z treats the whole command as one record, so `^` is the true command
# start — NOT the start of every heredoc line. Defense-in-depth for the
# uncaught cases: the Step-0 self-check + subagent-block-primary-writes.sh.
SEP='^[[:space:]]*'

is_switch=0

# gh pr checkout <N>
echo "$COMMAND" | grep -zqE "${SEP}gh[[:space:]]+pr[[:space:]]+checkout([[:space:]]|$)" && is_switch=1

# git switch ... — always moves HEAD (includes -c/-C/--detach).
echo "$COMMAND" | grep -zqE "${SEP}git[[:space:]]+switch([[:space:]]|$)" && is_switch=1

# git checkout ... — moves HEAD UNLESS it is a working-tree file restore.
if echo "$COMMAND" | grep -zqE "${SEP}git[[:space:]]+checkout([[:space:]]|$)"; then
  # File-restore forms that do NOT move HEAD (no `.*` — bounded so they can't
  # span across a separator into an unrelated `--` later in the command):
  #   git checkout -- <path>
  #   git checkout .
  #   git checkout <ref> -- <path>   (<ref> = one non-space token)
  if echo "$COMMAND" | grep -zqE "${SEP}git[[:space:]]+checkout[[:space:]]+--([[:space:]]|$)"; then
    :
  elif echo "$COMMAND" | grep -zqE "${SEP}git[[:space:]]+checkout[[:space:]]+\.([[:space:]]|$)"; then
    :
  elif echo "$COMMAND" | grep -zqE "${SEP}git[[:space:]]+checkout[[:space:]]+[^[:space:]]+[[:space:]]+--([[:space:]]|$)"; then
    :
  else
    is_switch=1
  fi
fi

[ "$is_switch" -eq 0 ] && exit 0

# --- 2. Where are we? primary vs a worktree ---
TOPLEVEL="$(git rev-parse --show-toplevel 2>/dev/null || true)"
[ -z "$TOPLEVEL" ] && exit 0  # not in a git repo → fail open

# A subagent operating in its OWN worktree may switch freely — isolated.
if [[ "$TOPLEVEL" == *"/.claude/worktrees/"* ]]; then
  exit 0
fi

# --- 3. Primary cwd. Orchestrator recovery escape hatch. ---
# Detected as a TOKEN IN THE COMMAND STRING, not an env var: a PreToolUse hook
# runs in the session env and does NOT inherit an inline `VAR=1 cmd` prefix, so
# an env-var check would never see it. Prefixing the command with
# `CLAUDE_ALLOW_CHECKOUT=1 ` both signals intent here AND (harmlessly)
# displaces the keyword off `^`.
if echo "$COMMAND" | grep -q 'CLAUDE_ALLOW_CHECKOUT=1'; then
  exit 0
fi

REASON="Branch-switch in the PRIMARY repo is blocked. The command ($COMMAND) would move the primary tree's HEAD — git checkout/switch and gh pr checkout retarget the shared branch state, and branch refs are shared across all worktrees, so this detaches the orchestrator's HEAD and can lock 'main' in another worktree (the cross-subagent branch-switch collision class). \
\
IF YOU ARE A SUBAGENT: you must operate only inside your own worktree under /.claude/worktrees/. Do not inspect PRs by switching the primary tree. Use read-only 'gh pr diff <N>' / 'gh pr view <N>', or run 'gh pr checkout <N>' inside your own worktree. If you've landed in primary by mistake, report MISBINDING to the orchestrator and stop. \
\
IF YOU ARE THE ORCHESTRATOR genuinely recovering branch state, prefix this single command with 'CLAUDE_ALLOW_CHECKOUT=1' to bypass the guard, e.g. 'CLAUDE_ALLOW_CHECKOUT=1 git checkout main'."

jq -n --arg r "$REASON" '{decision: "block", reason: $r}'
exit 0
