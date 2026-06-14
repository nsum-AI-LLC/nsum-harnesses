# Harness Design — a context-aware, self-enforcing Claude Code setup

> **What this is:** the design behind the hooks, scripts, agents, and skills in
> this repository. Read it to understand *why* each layer exists before wiring
> them into your project.
>
> **Where it came from:** extracted from a production project (willcall.ai),
> where it was built and hardened in daily use by a fleet of Claude Code agents.
> The comments in the code cite the failure modes that motivated each rule.

## Why this exists

A capable coding agent, left to its own devices, exhibits a predictable set of
failure modes:

1. **It skips context.** Told "read X before doing Y," it rationalizes that
   something already covered it and proceeds. Advisory reminders don't survive
   contact with the model's next directive-shaped instruction.
2. **It forgets across sessions.** A correction in one session doesn't make the
   same mistake less likely in the next — there's no memory and no learning loop.
3. **In multi-agent setups, it corrupts shared state.** Parallel subagents in
   git worktrees write the wrong tree, switch a shared branch, or make decisions
   on stale code from another branch.

This harness addresses each with *mechanics* rather than exhortation. It
separates **onboarding** (bootstrapping project knowledge at session start) from
**enforcement** (gating mid-session actions on having read the right things), and
adds a **learning loop** so the setup improves as humans catch drift.

One principle runs through all of it: **advisory text is not enforcement.** The
setup this replaced echoed "before proceeding, read X" and watched the model
proceed anyway. Anything you actually need to be true must be made true by a hook
that blocks, a log that remembers, or a check that runs — not by a sentence in a
prompt.

## Architecture — five layers

```
Layer 5: Session Briefing (SessionStart)
  One-shot "what's going on" — active work, recent commits, a suggested next
  action, and pending self-improvement proposals.

Layer 4: Context Cascade (hierarchical CLAUDE.md)
  Per-area CLAUDE.md files load along the path from the edited file up to the
  repo root. Local rules supersede global ones.

Layer 3: Precondition Gates (PreToolUse, blocking)
  Block Edit/Write/Skill/Agent until required reads are done. Logged bypass
  with a structured reason taxonomy.

Layer 2: Read-Tracking Log (PostToolUse on Read)
  Per-session record of what's been read. The foundation the gate and the
  self-improving hook both build on.

Layer 1: Self-Improving Hook (Stop)
  Reviews the session transcript and proposes harness/CLAUDE.md updates for a
  human to review. Never auto-applies.
```

## Layer-by-layer

### Layer 5 — Session Briefing

Goal: make the first minute of a session productive without the model navigating
the docs tree on demand.

- **Trigger:** SessionStart hook (`hooks/session-start.sh`)
- **Generator:** `scripts/session_briefing.py` → Markdown to stdout → session context
- **Sections:** active work, recent commits, recent status updates, pending
  self-improvement proposals, a heuristic next action, available specs
- **Fail-soft:** any section that can't be computed is omitted; session start
  never blocks on a briefing failure

The briefing assumes a `planning/` layout (`planning/sprints/`, `roadmap/`,
`specs/`); adapt the section functions to your project's structure. Because it's
fail-soft, unmatched sections simply don't appear.

### Layer 4 — Context Cascade

Goal: put context near the code it governs, so the model gets the relevant rules
automatically when it opens files in that area.

Place a `CLAUDE.md` at the repo root (global rules + a pointer table) and one in
each major code area (leading with that area's critical gotchas). Claude Code
loads each `CLAUDE.md` along the walk-up route from the edited file to the root,
so local rules supersede global ones. Keep the root file short; push specifics to
the leaves. A root file that grows to hundreds of lines is the anti-pattern this
avoids. See `examples/CLAUDE.md` for a template.

### Layer 3 — Precondition Gates

Goal: when the harness or a human needs the model to have read a specific file
before doing real work, enforce it mechanically.

- **Gate:** `hooks/precondition-gate.sh` — PreToolUse on `Edit|Write|Skill|Agent`
- **State:** `~/.cache/claude-harness/sessions/{session_id}/preconditions.json`
- **Block message:** stderr names each unsatisfied path, why it was required, and
  how to satisfy or bypass it
- **Read is never gated** (otherwise the model can't satisfy the gate — deadlock)
- **Bash is not gated** (read-only Bash like `git status` is too common; gating
  it would be disruptive)

Producers of preconditions: `claude_precondition <path> <reason>` (human-set).
Declaring required reads in skill/agent frontmatter is a natural extension (not
wired here).

Bypass (`claude_bypass <path> <category> [reason]`): categories `false_positive`,
`scope_limited`, `already_familiar`, `urgent_user_request`, `other`. Each appends
to `bypass.jsonl` for audit and marks the path satisfied for the session.

**Fail-open:** any script error allows the tool call.

### Layer 2 — Read-Tracking Log

Goal: maintain per-session state so the gate (and future analytics) can answer
"has the model read X this session?"

- **Tracker:** `hooks/read-tracker.sh` — PostToolUse on `Read`
- **Log:** `~/.cache/claude-harness/sessions/{session_id}/reads.jsonl`
  (one JSON line per read: `ts`, absolute `path`)

### Layer 1 — Self-Improving Hook (the Suggestion Collector)

Goal: close the loop. When a session surfaces a lesson (a human correction, a
bypassed reminder, a recurring mistake), propose the corresponding change for
next time. This is the component documented in full as the
[Suggestion Collector](suggestion-collector.md) — the one harness that checks the
*harness itself*.

- **Hook:** `hooks/self-improve.sh` — Stop event (fires after every model turn)
- **Reflector:** `scripts/reflect-on-transcript.py`
- **Output:** `~/.claude/{project}-proposals/{session_id}.md` — one file per
  session, overwritten on each firing, so it always reflects the latest analysis
- **Review:** `claude_proposals [list|view|clear]`

Detection is intentionally conservative — false positives erode trust faster than
missed lessons. It looks for correction phrases, "from now on / going forward"
phrasing, and signals that the model bypassed an advisory reminder in the prior
turn. Each signal produces a proposal with the correction text, the preceding
turn for context, and a suggested action. **The hook never auto-applies a
change — a human reviews and decides.**

## Worktree-safety hooks (for the orchestrator → worktree pattern)

If you run an orchestrator that dispatches subagents into isolated git worktrees,
shared branch refs and shared resources create collision classes these hooks
guard:

- `protect-worktree-planning.sh` — routes cross-cutting planning docs to the
  primary tree instead of a throwaway worktree branch
- `subagent-block-primary-writes.sh` — blocks a subagent from writing the primary
  tree via an absolute path
- `subagent-block-primary-reads.sh` (subagent-scoped) — blocks a subagent from
  *reading* the primary tree when a worktree twin exists, and returns the correct
  worktree path (stops the stale-cross-branch-read detour)
- `cross-worktree-read-guard.sh` — blocks reading another worktree's files
  (avoids decisions on stale, cross-branch code)
- `guard-branch-switch.sh` — blocks `git checkout`/`switch`/`gh pr checkout` from
  the primary CWD (branch refs are shared; a stray switch detaches the
  orchestrator's HEAD and can lock the main branch in another worktree)
- `guard-destructive-git.sh` — blocks `git worktree remove`/`prune` (these can
  delete a live worktree and crash editors)
- `guard-merged-push.sh` — warns before pushing an already-merged branch

The matching agent-side guard is the **Step-0 self-check** in
`agents/developer.md`: every subagent verifies it is actually in its worktree
before doing any work, and aborts with `MISBINDING` if the platform misplaced it.
A mechanical hook plus an agent self-check together cover the realistic failure
shapes; either one alone has gaps.

When a session is reaped mid-flight, the recovery tools in `scripts/` —
`harvest_unpushed_worktree_commits.sh`, `prune_worktrees.sh`, and
`audit_session_commits.sh` — recover stranded work, prune accumulated worktrees
safely, and audit for lost commits. The full topology, the collisions it prevents,
and these tools are documented in [`worktrees.md`](worktrees.md).

## Fail-open philosophy

Every hook catches its own errors and exits 0 if anything goes wrong. The gate
exits non-zero *only* when it deliberately blocks. A broken gate that blocks every
tool call is worse than no gate — so the failure mode is "stops enforcing," never
"stops working." The trade-off: none of these hooks is a hard guarantee. Under a
script error or environment drift the guarded action proceeds. Treat them as
strong defaults, not a security boundary.

## State files

All under `~/.cache/claude-harness/sessions/{session_id}/`:

| File | Format | Purpose |
|---|---|---|
| `reads.jsonl` | JSONL `{ts, path}` | append-log of Read tool calls |
| `preconditions.json` | JSON `{required_reads: [...]}` | unsatisfied required reads |
| `bypass.jsonl` | JSONL `{ts, path, category, reason}` | logged bypasses |

Self-improvement proposals live separately, per project, at
`~/.claude/{project}-proposals/{session_id}.md` (project = basename of
`$CLAUDE_PROJECT_DIR`).

## File inventory

| Path | Purpose |
|---|---|
| `hooks/read-tracker.sh` | PostToolUse on Read → reads.jsonl |
| `hooks/precondition-gate.sh` | PreToolUse → block when preconditions unmet |
| `hooks/self-improve.sh` | Stop → reflect on transcript, write a proposal |
| `hooks/cross-worktree-read-guard.sh` | PreToolUse on Read → block cross-worktree reads |
| `hooks/protect-worktree-planning.sh` | PreToolUse → route planning writes to primary |
| `hooks/subagent-block-primary-writes.sh` | PreToolUse (subagent) → block primary writes |
| `hooks/subagent-block-primary-reads.sh` | PreToolUse on Read (subagent) → block primary reads, redirect to the worktree |
| `hooks/guard-branch-switch.sh` | PreToolUse on Bash → block branch switch in primary |
| `hooks/guard-destructive-git.sh` | PreToolUse on Bash → block destructive worktree ops |
| `hooks/guard-merged-push.sh` | PreToolUse on Bash → warn on pushing a merged branch |
| `hooks/session-start.sh` | SessionStart → invoke the briefing |
| `scripts/precondition_state.py` | read/write state for the gate |
| `scripts/reflect-on-transcript.py` | transcript analysis for the self-improving hook |
| `scripts/session_briefing.py` | generate the session-start briefing |
| `scripts/harvest_unpushed_worktree_commits.sh` | recover commits/writes stranded by a reaped session |
| `scripts/prune_worktrees.sh` | sanctioned worktree removal (dry-run first) |
| `scripts/audit_session_commits.sh` | audit a session for lost commits / primary-tree contamination |
| `scripts/claude_precondition` | CLI: add a required-read precondition |
| `scripts/claude_bypass` | CLI: log a bypass |
| `scripts/claude_proposals` | CLI: review self-improvement proposals |
| `agents/` | subagent definitions (developer, code-reviewer, system-analyst) |
| `skills/` | skills (groom-ticket, orchestrate, code-review, architect-reminder, stepping-away, summarize-issue, review-suggestions) |
| `workflows/ticket-review-panel.js` | the adversarial pre-dispatch review panel |
| `examples/CLAUDE.md` | Context Cascade template |
| `settings.example.json` | example hook wiring |

## Adoption checklist

1. Copy `hooks/` → `.claude/hooks/` and `scripts/` → `.claude/scripts/` (put the
   `claude_*` CLIs on your PATH).
2. Merge the `hooks` block from `settings.example.json` into `.claude/settings.json`.
3. Adopt the Context Cascade: a short root `CLAUDE.md` plus a per-area `CLAUDE.md`
   that leads with critical gotchas.
4. (Optional) Copy `agents/developer.md` and `skills/groom-ticket/` for the
   orchestrator → worktree workflow.
5. Exercise the gate once: set a precondition, attempt an Edit (should block),
   Read the file (should clear), Edit again (should pass).

## Beyond enforcement — the role constellation

The hooks and gates above are the *enforcement layer*: they make context-reading,
worktree isolation, and self-improvement mechanical instead of advisory. On top of
that layer sits a constellation of **agents and skills** that check each other's
work — a groomer, a behavior-tracing analyst, an adversarial review panel, a
developer, a code-reviewer, an orchestrator. The enforcement hooks are what make
those roles' hand-offs trustworthy (a subagent really is sandboxed; a required
read really happened).

- **The principle** — why no single role is trusted, and how they hold each other
  accountable — is in [`checks-and-balances.md`](checks-and-balances.md). Read it
  first.
- **The roles in motion** — one ticket's lifecycle through grooming, the analyst,
  the panel, the developer, and the reviewer — is in
  [`development-loop.md`](development-loop.md).
- **The worktree topology** the orchestration roles rely on, the collisions it
  prevents, and the recovery tools are in [`worktrees.md`](worktrees.md).
- **Running unattended** — handing the loop a plan and stepping away — is in
  [`autonomous-operation.md`](autonomous-operation.md).

The relevant files: `agents/system-analyst.md`, `agents/code-reviewer.md`,
`agents/developer.md`, `skills/groom-ticket/`, `skills/orchestrate/`,
`skills/code-review/`, `skills/architect-reminder/`, `skills/stepping-away/`,
`skills/summarize-issue/`, and `workflows/ticket-review-panel.js`.

## What this does NOT solve

- **It is not a security boundary.** Fail-open means a broken or bypassed hook
  lets the action through.
- **It assumes some conventions.** The briefing and a few hooks expect a
  `planning/` layout and a primary → worktree topology. Adapt them to your project.
- **Intent detection is deliberately simple.** The self-improving hook uses
  keyword/phrase signals, no model in the loop, to keep hooks fast and cheap. It
  errs toward missing lessons over crying wolf.
- **It governs Claude Code's own tool calls** (Bash/Edit/Write/Read/Skill/Agent).
  Operations through other tools that don't fire these events are out of scope.
