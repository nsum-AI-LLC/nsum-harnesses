#!/usr/bin/env bash
# PreToolUse hook on the Agent dispatch tool: block a developer dispatch whose
# ticket carries no verified current-behavior trace and claims no exemption.
#
# Why this exists. `orchestrate` Phase 0 already requires that every load-bearing
# current-behavior assertion be backed by a ⟦SYSTEM-ANALYST-VERIFIED⟧ signature,
# and calls the requirement mechanical rather than advisory. It is not mechanical:
# the orchestrator that just wrote the ticket is the same party that decides
# whether the ticket is ready, and a session confident in its own greps skips the
# check without noticing. Two P0 tickets were dispatched on grep-derived
# mechanisms on 2026-09-06 while the rule sat in the skill unquoted.
#
# A symptom can be measured from a grep. A MECHANISM cannot, and the fix is built
# on the mechanism. That is the whole reason for the signature chain.
#
# Decision matrix (developer dispatches only — read-only agents write no code):
#   - tool is not Agent/Task, or subagent_type != developer -> ALLOW (fail open)
#   - no target ticket id resolvable                        -> ALLOW
#   - the ticket file cannot be found or read               -> ALLOW (cannot judge)
#   - ticket carries ⟦SYSTEM-ANALYST-VERIFIED⟧              -> ALLOW
#   - ticket carries ⟦NO-BEHAVIORAL-CLAIMS⟧                 -> ALLOW (claimed exemption)
#   - otherwise                                             -> BLOCK
#
# The exemption is a TOKEN the author writes, not a silence the hook infers. A
# purely additive ticket asserting nothing about existing behavior is exempt by
# the skill's own rule, and its author says so in one line. Nothing here judges
# whether a ticket makes behavioural claims — that judgement belongs to the
# author; this only refuses to let the question go unanswered.
#
# TARGETING follows guard-redispatch-fork.sh: the dispatch TARGET from
# `description` first, else the FIRST ticket id in the prompt. A developer prompt
# names many CONTEXT tickets; scanning all of them false-blocks on those.

INPUT=$(cat)

TOOL=$(echo "$INPUT" | jq -r '.tool_name // ""' 2>/dev/null)
[ "$TOOL" = "Agent" ] || [ "$TOOL" = "Task" ] || exit 0

SUBAGENT=$(echo "$INPUT" | jq -r '.tool_input.subagent_type // ""' 2>/dev/null)
[ "$SUBAGENT" = "developer" ] || exit 0

DESC=$(echo "$INPUT"   | jq -r '.tool_input.description // ""' 2>/dev/null)
PROMPT=$(echo "$INPUT" | jq -r '.tool_input.prompt // ""'      2>/dev/null)

# Conscious override, matching the sibling guard's escape-hatch convention.
printf '%s %s' "$DESC" "$PROMPT" | grep -qiF '[trace-ok]' && exit 0

TICKET=$(printf '%s' "$DESC"   | grep -oE '\b[A-Z]{2,5}-[0-9]+\b' | head -1)
[ -z "$TICKET" ] && TICKET=$(printf '%s' "$PROMPT" | grep -oE '\b[A-Z]{2,5}-[0-9]+\b' | head -1)
[ -z "$TICKET" ] && exit 0

ROOT="${CLAUDE_PROJECT_DIR:-$(pwd)}"
FILE=$(find "$ROOT/planning/roadmap" -name "${TICKET}-*.md" -o -name "${TICKET}.md" 2>/dev/null | head -1)
[ -z "$FILE" ] && exit 0
[ -r "$FILE" ] || exit 0

grep -qF '⟦SYSTEM-ANALYST-VERIFIED⟧' "$FILE" && exit 0
grep -qF '⟦NO-BEHAVIORAL-CLAIMS⟧'    "$FILE" && exit 0

REL=${FILE#"$ROOT"/}
REASON=$(printf 'BLOCKED: %s carries no verified current-behavior trace and claims no exemption.\n\n  ticket: %s\n\nA symptom can be measured from a grep; a MECHANISM cannot, and the fix is built on the mechanism. `orchestrate` Phase 0 requires every load-bearing current-behavior assertion to be backed by a ⟦SYSTEM-ANALYST-VERIFIED⟧ signature whose covers= scope includes the claim.\n\nDo ONE of these:\n\n  1. Dispatch the system-analyst (subagent_type: system-analyst) with the precise\n     behavioural question, then paste its report AND its signature line verbatim\n     into a "Current Behavior (verified)" section of the ticket.\n\n  2. If the ticket genuinely asserts nothing about how existing code behaves —\n     purely additive design — write the token ⟦NO-BEHAVIORAL-CLAIMS⟧ into it, on\n     a line saying so. That is the skill'"'"'s own exemption, claimed rather than\n     assumed.\n\nOverride with the literal token [trace-ok] in the prompt only when the trace\nexists somewhere this hook cannot see.' "$TICKET" "$REL")

jq -n --arg r "$REASON" '{decision: "block", reason: $r}'
exit 0
