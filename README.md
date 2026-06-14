# nsum-harnesses

The context, enforcement, and self-improvement harness developed by the [nsum.ai](https://nsum.ai) team
while building [willcall.ai](https://willcall.ai).

This is a **reference implementation**. © 2026 nsum. All rights reserved.

## Why this exists

These harnesses control reliability and quality when you apply the leverage that frontier models and
agentic workflows unlock for software development. Today's frontier models have properties that need to be
kept in check, especially in long-running development loops:

- **Sycophancy and gullibility.** The models aim to please and are overly trusting. That's a risk when you
  trust one to make — or to scrutinize — architectural decisions.
- **Amnesia.** A new session starts from scratch, and the more mature a project is, the worse a "cold
  start" gets. Strategy, architecture, and established conventions have to be re-learned every session.
- **Compounding errors.** Without correcting for the above, an early mistake in a long autonomous run
  snowballs into a wasted session or a latent architectural flaw.
- **Completion drive.** The model wants to deliver what you asked for. If you give up control of
  "definition of done" or stop enforcing best practices, you risk the wrong result, poor implementation
  decisions, or both.

## The big idea: checks and balances

You can't prompt these failure modes away. "Always verify," "always follow best practices" are advice, and
advice doesn't survive the model's next instruction. So the harness doesn't depend on one agent getting
everything right: each fact is checked by a different role than the one that produced it, through a
mechanism — a hook that blocks, a signature that's grepped for, a checklist that must be completed.

There's no guarantee a developer follows every best practice, so the code-reviewer checks. There's no
guarantee a ticket was groomed with testable acceptance criteria, so the developer and orchestrator both
check. There's no guarantee an author traced the code they describe, so the system-analyst traces it and
signs the result.

[`docs/checks-and-balances.md`](docs/checks-and-balances.md) explains the pattern and how to apply it to
your project. Read it first.

## Who it's for

Anyone running Claude Code (or a similar agentic coding harness) on a real codebase, who wants discipline
and safety enforced *by the harness* instead of by trust and hope. Use these tools to establish your
project's own quality standards and development procedures, and to make them persist over time.

## What's inside

### Tier 1 — Context & self-improvement (drop-in for any project)

| Component | What it does |
|---|---|
| Context Cascade (`examples/CLAUDE.md`) | per-directory `CLAUDE.md` files that load along the path from the file you're editing up to the repo root |
| Read-tracking log (`hooks/read-tracker.sh`) | records every file the agent reads in a session |
| Precondition gates (`hooks/precondition-gate.sh`, `scripts/precondition_state.py`, `scripts/claude_precondition`, `scripts/claude_bypass`) | block Edit/Write/Skill/Agent until required reading is done; bypasses are logged with a reason taxonomy |
| Session briefing (`hooks/session-start.sh`, `scripts/session_briefing.py`) | a short "what's going on" injected at session start |
| **Suggestion Collector** (`hooks/self-improve.sh`, `scripts/reflect-on-transcript.py`, `scripts/claude_proposals`) | reflects on each session, writes improvement proposals, surfaces them at the next session start — the harness that improves the harness. See [`docs/suggestion-collector.md`](docs/suggestion-collector.md) |

### Tier 2 — Orchestration safety (for the orchestrator → worktree pattern)

Why this matters and the real collisions it prevents: [`docs/worktrees.md`](docs/worktrees.md).

| Component | What it does |
|---|---|
| Worktree isolation hooks (`hooks/protect-worktree-planning.sh`, `subagent-block-primary-writes.sh`, `subagent-block-primary-reads.sh`, `cross-worktree-read-guard.sh`, `guard-branch-switch.sh`, `guard-destructive-git.sh`, `guard-merged-push.sh`) | stop subagents from writing or reading the primary tree, switching its branch, deleting worktrees, or reading another worktree's files |
| Recovery & maintenance (`scripts/harvest_unpushed_worktree_commits.sh`, `prune_worktrees.sh`, `audit_session_commits.sh`) | recover work stranded by a reaped session, prune accumulated worktrees safely, and audit a messy session for lost commits |
| `developer` agent (`agents/developer.md`) | an implementer subagent with a mandatory "am I in my own worktree?" self-check that aborts if misplaced |
| `groom-ticket` skill (`skills/groom-ticket/`) | turns a rough idea into a fully-specified ticket an agent can build from with no extra context |

### Tier 3 — The review & verification constellation (the checks and balances)

The roles that hold each other accountable through a ticket's lifecycle. Walkthrough:
[`docs/development-loop.md`](docs/development-loop.md).

| Component | What it does | What it checks |
|---|---|---|
| `system-analyst` agent (`agents/system-analyst.md`) | read-only; traces how existing code *actually* behaves and signs the result (`⟦SYSTEM-ANALYST-VERIFIED⟧`) | replaces "the author says…" with a signed, `file:line`-cited trace |
| `ticket-review-panel` workflow (`workflows/ticket-review-panel.js`) | spawns N independent reviewers with diverse lenses against a groomed ticket *before* dispatch | catches a bad approach before any code is written |
| `code-reviewer` agent + `code-review` skill (`agents/code-reviewer.md`, `skills/code-review/`) | the three-layer review (SHOULD → DOES → SURVIVES) with upstream/downstream tracing and a non-negotiable checklist | that best practices were actually followed |
| `orchestrate` skill (`skills/orchestrate/`) | drives the loop; gates ticket readiness before dispatch; dispositions every finding after review | that no half-groomed ticket is built and no finding is left unaddressed |
| `architect-reminder` skill (`skills/architect-reminder/`) | forces a merit-only re-derivation of a recommendation | that "that's a lot of work" never masquerades as a design reason |
| `stepping-away` + `summarize-issue` skills (`skills/stepping-away/`, `skills/summarize-issue/`) | hand the session an autonomous mandate; knock with a 2-minute door-knock briefing only at a hard gate | that unattended runs still run the full loop and stop precisely at irreversible decisions |

The autonomy workflow — handing the loop a plan and stepping away — is in [`docs/autonomous-operation.md`](docs/autonomous-operation.md).

## Layout

```
hooks/                  # bash hooks (project-level + subagent-scoped)
scripts/                # python + bash helpers, claude_* CLIs, worktree recovery tools
agents/                 # subagent definitions (developer, system-analyst, code-reviewer)
skills/                 # skills (groom-ticket, orchestrate, code-review, architect-reminder,
                        #         stepping-away, summarize-issue, review-suggestions)
workflows/              # Workflow scripts (ticket-review-panel)
examples/CLAUDE.md      # Context Cascade template
settings.example.json   # example hook wiring
docs/
  checks-and-balances.md   # ★ the overarching principle — read first
  development-loop.md      # the roles in motion, one ticket end to end
  worktrees.md             # the orchestrator → worktree topology, its collisions, and the tools
  autonomous-operation.md  # handing the loop a plan and stepping away
  harness_design.md        # the enforcement layer: hooks, gates, fail-open philosophy
  code-review.md           # the layered review method + how to grow it toward your stack
  suggestion-collector.md  # the self-improving loop
```

## Quick start

1. Copy `hooks/` to your project's `.claude/hooks/` and `scripts/` to `.claude/scripts/`. Put the
   `claude_*` CLIs on your `PATH` if you want to call them directly.
2. Merge the `hooks` block from `settings.example.json` into your `.claude/settings.json`.
3. Adopt the Context Cascade: drop a root `CLAUDE.md` (see `examples/CLAUDE.md`) and add a per-area
   `CLAUDE.md` to each major code directory.
4. For Tier 2/3, copy `agents/` → `.claude/agents/`, `skills/` → `.claude/skills/`, and (if you use the
   Workflow tool) `workflows/` → `.claude/workflows/`. These assume an orchestrator → worktree topology;
   the worktree hooks (Tier 2) make that isolation real. **Adapt the conventions** in each agent/skill —
   ticket-ID format, where plans live, your forge CLI — to your project.
5. Read [`docs/checks-and-balances.md`](docs/checks-and-balances.md) for the principle, then
   [`docs/development-loop.md`](docs/development-loop.md) for how the roles run, and
   [`docs/harness_design.md`](docs/harness_design.md) for the enforcement layer.

Every hook is **fail-open**: if a script errors, it exits 0 and your tool call proceeds. A broken gate
that blocks everything is worse than no gate. Read each hook before you wire it in — they run shell on
your machine and can block your tools.
