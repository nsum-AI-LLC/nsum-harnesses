---
name: review-suggestions
description: "Review and act on the harness-improvement proposals collected by the Suggestion Collector (the self-improving Stop hook). Run this on your own schedule — it discovers pending proposals across all projects, clusters them into distinct lessons, drafts concrete fixes (a CLAUDE.md rule, a new hook, a skill tweak, or 'dismiss'), applies the ones you approve, and clears what's been handled. Use when the user wants to review/triage harness suggestions, process proposals, or 'see what the harness learned'."
---

# Review Suggestions Skill

The [Suggestion Collector](../../docs/suggestion-collector.md) writes a proposal after every session into
`~/.claude/{project}-proposals/{session_id}.md` — automatically, in the background. **Collection is a
push; review is a pull.** This skill is the pull: a deliberate, user-initiated pass to turn that pile of
raw signals into a small number of concrete harness changes (or dismissals), so the proposals never just
accumulate unread.

The detector is conservative but still pattern-based — expect a meaningful fraction of false positives, and
expect the *same* lesson to recur across many session files.
Your job is to compress N proposal files into a handful of distinct, actionable lessons and drive each to a
decision. **You propose; the user disposes.** Never apply a change to a CLAUDE.md, hook, or settings file
without explicit approval — these edits persist and shape every future session.

## Step 1 — Discover what's pending

Scope: **all projects by default** (the point of this workflow is to clear the backlog everywhere). If the
user asked to limit it to the current project, do that instead.

List the pending proposals with their project and recency:

```bash
for d in "$HOME"/.claude/*-proposals; do
  [ -d "$d" ] || continue
  proj=$(basename "$d"); proj=${proj%-proposals}
  for f in "$d"/*.md; do
    [ -e "$f" ] || continue
    printf '%s\t%s\t%s\n' "$(date -r "$f" +%Y-%m-%d)" "$proj" "$f"
  done
done | sort -r
```

If nothing prints, tell the user there are no pending proposals and stop. Otherwise report the count per
project and the date range, so the user knows the size of the backlog before you dig in.

## Step 2 — Read and cluster into distinct lessons

Read each proposal file (the Read tool). Each contains one or more signals: the matched patterns, an
excerpt of the assistant turn that preceded the user's correction, and the correction itself.

Then **cluster**. Group signals that express the same underlying lesson, even across different sessions and
projects. Five proposal files that all say "you edited without reading the spec first" are *one* lesson,
not five. For each cluster, capture:

- **The lesson** — what the user actually wanted changed, in one sentence.
- **How often / where** it recurred (counts, projects, dates) — frequency is evidence it's real, not noise.
- **The source files** — which proposal files belong to this cluster (you'll clear them in Step 5).

Discard, in your own analysis, signals that are clearly false positives (the pattern matched but the user
wasn't correcting harness behavior) — but keep their files in a "dismiss" bucket so you can clear them too.

## Step 3 — Decide the fix for each lesson

For each distinct lesson, choose the **lowest-friction mechanism that actually enforces it**:

| If the lesson is… | The fix is usually… |
|---|---|
| A recurring behavior the rules should prevent, and a rule would be obeyed | A line in `CLAUDE.md` — the **sub-area** file closest to the code it governs, else the root |
| Something the model bypassed *despite* a written reminder | A **hook** that blocks or redirects — advice already failed; make it mechanical |
| A skill/agent doing the wrong thing or missing a step | An edit to that **skill/agent** definition (its description or procedure) |
| Generic enough to help every project | A change to your **shared tooling** source, then re-synced to consumers |
| A one-off, or a false positive | **Dismiss** — no change; just clear it |

The key judgment: **if the model talked past an advisory reminder, "say it louder" is the wrong fix.** That
is exactly the signal to make it a hook. (That insight is the origin of this whole harness.)

Identify the **target project** for each fix — the lesson may have come from a different project than the
session you're running this in. Route the edit to that project's files (absolute paths are fine).

## Step 4 — Propose, then apply on approval

Present a compact decision queue to the user — grouped by target, ordered by frequency/impact. For each
lesson:

- The one-sentence lesson and how often it recurred.
- The **concrete change**, written out: the exact CLAUDE.md line and which file it goes in; or the hook
  (name, event, what it blocks); or the skill/agent edit. Write it out in full, ready to apply.
- A one-line rationale.

Ask the user which to apply, edit, or skip. Then **apply only the approved changes**:

- CLAUDE.md / skill / agent edits → Edit the target file directly.
- A new hook → write the script under the target project's `.claude/hooks/`, and add its wiring to
  `settings.json` (or show the user the settings block to merge, if you can't safely edit it).
- Shared-tooling fixes → make the change in the tooling source and tell the user to re-sync consumers.

Keep applied changes minimal and consistent with the surrounding file's style.

## Step 5 — Clear what you handled

Clear every proposal file you dispositioned — both the ones turned into changes and the ones dismissed.
Leave untouched only proposals the user explicitly deferred.

- **Current project:** `claude_proposals clear <prefix>` (substring match on the session-id filename), or
  `claude_proposals clear` to clear the whole current-project bucket.
- **Other projects:** the CLI is per-project, so remove those files directly:
  `rm "$HOME"/.claude/<project>-proposals/<session_id>.md`.

Clearing is how the backlog stays meaningful — an un-pruned pile of stale proposals trains you to ignore
the whole mechanism.

## Step 6 — Summarize

Report: lessons found (with counts), changes applied (file + what changed), items dismissed, items
deferred (and why), and any fix that belongs in shared tooling and should propagate to other projects.
This summary is the record of what the harness learned this round and how you responded.
