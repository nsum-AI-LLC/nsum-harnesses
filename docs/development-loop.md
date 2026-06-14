# The Development Loop — the roles in motion

This is the practical companion to [`checks-and-balances.md`](checks-and-balances.md). That doc explains
*why* the roles check each other; this one walks through *how* they run, end to end, on a single ticket —
and how to adopt and customize each one.

## The cast

| Role | Type | What it does | Key check it performs |
|---|---|---|---|
| **groom-ticket** | skill | Turns a rough idea into a self-contained implementation brief | Challenges the premise; verifies current-behavior claims via the analyst |
| **system-analyst** | agent (read-only) | Traces how existing code *actually* behaves; signs the result | Replaces "the author says…" with "an agent traced it and signed it" |
| **ticket-review-panel** | workflow | N independent reviewers attack the groomed ticket pre-dispatch | Catches a bad approach before any code is written |
| **orchestrate** | skill | Drives the whole loop; gates ticket readiness; dispositions findings | Refuses to build on a half-groomed ticket; no finding dies |
| **developer** | agent | Implements one ticket in an isolated worktree | Self-checks placement; refuses unsigned behavioral claims |
| **code-reviewer** | agent | Invokes the code-review skill; posts findings (no overall verdict) | Enforces that best practices were actually followed |
| **architect-reminder** | skill | Re-derives a recommendation on merit, stripping cost-gating | Catches "that's a lot of work" masquerading as a design reason |

Each is a single Markdown file you can read, edit, and adopt independently. Agents live in `agents/`,
skills in `skills/<name>/SKILL.md`, the panel in `workflows/`.

## One ticket, start to finish

```
        ┌─────────────┐
        │ groom-ticket│  rough idea → buildable brief
        └──────┬──────┘
               │ correctness depends on existing behavior?
               ▼
        ┌─────────────┐
        │system-analyst│  trace it, sign it  ⟦SYSTEM-ANALYST-VERIFIED⟧
        └──────┬──────┘
               │ embed signed report in the ticket
               ▼
        ┌─────────────┐
        │   panel?    │  high-sensitivity ticket → adversarial review (BLOCK/REVISE/READY)
        └──────┬──────┘
               ▼
   ┌───────────────────────── orchestrate ─────────────────────────┐
   │  Phase 0  readiness gate  (incl. signature gate 0a′)           │
   │  Phase 1  dispatch developer  ──►  isolated git worktree       │
   │  Phase 2  open PR            (orchestrator NEVER merges)       │
   │  Phase 3  code-reviewer  ──►  three layers + checklist         │
   │  Phase 4  architect evaluation  (every finding dispositioned)  │
   │  Phase 5  fix cycle  ──►  developer pushes to the SAME branch  │
   │  Phase 6  "ready to merge"  ──►  reported to the user          │
   │  Phase 7  status update                                        │
   └───────────────────────────────────────────────────────────────┘
               │
               ▼
        ┌─────────────┐
        │  Stop hook  │  suggestion collector reflects → proposal for next time
        └─────────────┘
```

### 1. Groom (`skills/groom-ticket`)

A well-groomed ticket is a knowledge-transfer document: a zero-context developer reads it and knows what
to build, why, and how to verify it. Grooming gathers context, **challenges the premise** (the output can
legitimately be "don't build this"). When the ticket's correctness depends on how existing code behaves, it
dispatches the **system-analyst** instead of asserting that behavior from a grep.

### 2. Verify current behavior (`agents/system-analyst`)

A read-only agent that traces the *actual* execution path hop by hop, cites `file:line`, separates
verified from inferred, and ends with a signature:

```
⟦SYSTEM-ANALYST-VERIFIED⟧ topic="…" date="…" run="…" covers="…"
```

That report and signature get pasted into the ticket's **Current Behavior (verified)** section. From here
on, three roles refuse to trust an unsigned behavioral claim — the [signature chain](checks-and-balances.md#a-worked-example-the-signature-chain).

Dispatch it with the Agent tool: `subagent_type: system-analyst`, with one precise behavioral question
(or a few). The orchestrator, the grooming skill, and even the developer are all allowed to call it.

### 3. (High-sensitivity only) Run the adversarial panel

See [the panel section below](#the-adversarial-ticket-review-panel). Skip it for routine tickets; run it
before dispatching a developer on anything irreversible, wide-blast-radius, or resting on a contested
design fork.

### 4–7. Orchestrate (`skills/orchestrate`)

The orchestrator is the hub. It **gates ticket readiness before dispatch** (Phase 0 — including the
signature gate 0a′), dispatches **developers** into isolated worktrees, opens PRs (but **never merges**),
runs the **code-reviewer**, and **dispositions every finding** (Phase 4): no finding is "noted" — every one
is fixed now or explicitly ticketed. Fixes go back to the *same* PR branch; non-trivial fixes get
re-reviewed.

### The developer (`agents/developer`)

Implements one ticket end to end in its own worktree. Its first action is a **Step-0 self-check** — it
runs `git rev-parse --show-toplevel` and aborts with `MISBINDING` if the platform misplaced it in the
primary tree. It separates decision logic from persistence, batches writes, tests decisions (not the
framework), and persists with an **atomic `git commit && git push`** so a reaped session can't strand a
commit. It also refuses to build on an unsigned current-behavior claim.

### The code-reviewer (`agents/code-reviewer`) + the review skill

The reviewer is a thin coordinator: it invokes the **code-review skill**, ensures the checklist is
complete, posts the review as a PR comment, and reports structured findings. It renders **no overall
verdict** — evaluating the findings and deciding what to do belongs to the orchestrator (see
[`code-review.md`](code-review.md#no-overall-verdict--and-why)). The substance — the three layers
(SHOULD → DOES → SURVIVES), the upstream baseline diff, the downstream caller search, the non-negotiable
checklist — lives in the skill.

### architect-reminder (`skills/architect-reminder`)

Not part of the linear flow — a *reflex*. Invoke it any time a recommendation between options is being
written, especially if "ship now / iterate later," "defer," or "that's a lot of work" appears. It forces
the decision to be re-derived on merit, with cost/timeline/sunk-cost factors explicitly stripped out.

## The adversarial ticket-review panel

`workflows/ticket-review-panel.js` is a [Workflow](https://docs.claude.com/en/docs/claude-code) script: it
spawns **N independent reviewers in parallel**, each with a *different lens*, against a groomed ticket
**before** any developer is dispatched. None of them wrote the ticket; each is told to review on merit, as
if resources were unlimited, and to produce a steelman of the strongest alternative even if it finds
little else wrong.

**Why a panel, not one reviewer.** A single reviewer has a single blind spot. Three reviewers with
*diverse* lenses — is the approach right, is it safe, does it fit the strategy and is it groomed enough —
catch failure modes that redundancy alone can't. The lenses are deliberately different jobs, not three
copies of the same job.

**The default lenses** (edit them in the script's `LENSES` array):

- **`fork-merit`** — Is the chosen path genuinely best, on merit? Steelman each dismissed alternative
  under the unlimited-resources test. Flag cost-gating red flags in the ticket's own reasoning.
- **`safety-blast-radius`** — What must be true that the ticket never verifies? Could it mutate or run
  wider than intended, destroy data, act irreversibly without a backup? Is it idempotent, reversible,
  observable?
- **`strategy-groom`** — Does it serve the product strategy or a local metric? Is it self-contained for a
  zero-context developer? Are the acceptance criteria testable and split ships-with / runs-after? Do
  current-behavior claims carry a signature?

**How to run it.** Invoke the Workflow tool with this script and pass an **absolute** ticket path:

```
ticket-review-panel  args: { "ticketPath": "/abs/path/to/ticket.md", "fork": "the design fork it resolves" }
```

The absolute-path requirement is enforced (the script throws on a relative path): a relative path can
resolve against a stale worktree left by a prior agent, and the panel would silently review the *wrong*
ticket.

**What you get back** — a structured object: each lens's `verdict` (READY / REVISE / BLOCK), its findings
(each with a `severity`, the concrete `failure_mode` it guards against, and a `suggested_resolution`), its
`steelman`, and a top-level `complete` flag. **`complete` is false if any lens failed to return** — a
stalled reviewer is silence, not approval, so the script retries each lens up to five times and tells you
if the panel is not trustworthy. Resolve every `blocking` finding before dispatching the developer.

**Customizing the panel.** Add or replace lenses for the risks *your* projects actually face (a
data-integrity lens, a security lens, a migration-safety lens). Change `maxAttempts`, or the verdict
enum, to taste. Keep the two structural choices that make it work: independent reviewers (no shared
context) and "incomplete panel ≠ approval."

## Adopting these roles

These roles assume an **orchestrator → worktree** topology: a primary session that plans and delegates,
and subagents that each run in their own isolated git worktree. That topology is what the
[worktree-safety hooks](harness_design.md#worktree-safety-hooks-for-the-orchestrator--worktree-pattern)
protect. To adopt:

1. Copy `agents/` to `.claude/agents/` and `skills/` to `.claude/skills/`. Copy `workflows/` if you use
   the Workflow tool.
2. **Adapt the conventions.** Every role refers to tickets, sprints/iterations, and a forge CLI (`gh`)
   with example strings. Replace them with yours — ticket-ID format, where plans and tickets live, your
   forge. The *structure* (readiness gate → dispatch → review → disposition) is the part to keep.
3. **Wire the worktree hooks** so the developer/reviewer/analyst isolation is enforced, not just
   described (see `settings.example.json` and [`harness_design.md`](harness_design.md)).
4. **Grow the code-review checklist toward your stack** — that's where most of the project-specific value
   lives. See [`code-review.md`](code-review.md#customizing-this-skill).
