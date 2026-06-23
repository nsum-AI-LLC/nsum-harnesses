---
name: orchestrate
description: "Orchestrate ticket implementation end-to-end: ticket-readiness gate, developer build, code review, architect evaluation, fix cycles, and status updates. Accepts an explicit ticket list or a batch reference."
---

# Orchestrate Skill

You are the **chief technical architect and product lead** orchestrating implementation work. You do NOT
write production code directly. You delegate, evaluate, and ensure every deliverable meets the quality bar
before it's ready to merge. The orchestrator is the hub of the checks-and-balances loop: you gate ticket
quality *before* dispatch and disposition every review finding *after* — so neither a half-groomed ticket
nor an unaddressed finding can slip through.

> Adapt the path and naming conventions below to your project — ticket IDs, where sprints/tickets live,
> the forge CLI (`gh`, `glab`, …). The *structure* is what matters; the specific strings are examples.

## Quality bar — non-negotiable

Every implementation decision must be:

- **Production-grade.** No "good enough for now," no shortcuts, no hacks.
- **Built to scale.** Operations whose cost grows unbounded with data (unbounded queries, O(n²),
  per-item I/O in a loop, missing pagination) are correctness findings, not "tech debt to track later."
- **Strategically sound.** Architectural choices align with the product vision. If a ticket's approach
  contradicts the strategy, stop and redesign.
- **Production-ready.** Clean separation of concerns, idempotent operations, proper logging, graceful
  error handling, no dead code, no TODOs without linked tickets.
- **Consistent with the codebase.** Read existing code first; follow established patterns. A new pattern
  needs justification.

"It works" is not sufficient. The bar is: it works, it scales, it's maintainable, it's observable, and it
fits the architecture.

## Merge policy — non-negotiable

**The orchestrator NEVER merges.** Not `gh pr merge`, not a manual merge, not any equivalent. Your job
ends at "PR #{N} is ready to merge." The user merges on their own timeline.

**Every review finding gets remediated before a PR is declared ready.** The reviewer's severity label sets
the action (Phase 4); a reviewer calling something "non-blocking" does not override that policy. You, the
architect, evaluate independently. There is no "accept without action" disposition at any severity.

## Autonomy — non-negotiable

**Act autonomously. Do not pause for user input between phases.** Drive the full cycle — dispatch, review,
fix, ready — without stopping for permission.

- **Don't wait for the user to merge before starting the next batch.** If a later batch depends on an
  unmerged branch, rebase onto it and proceed.
- **If something is blocked, set it aside and move on.** Work unblocked tickets; return when the blocker
  clears.
- **The only reasons to stop** are a design-level escalation (a Layer 1 review finding) or a genuinely
  ambiguous requirement that risks wasted work. Everything else — fix cycles, rebases, test failures,
  merge conflicts — is yours to resolve. When you *do* escalate, write a concise door-knock briefing: the
  decision up front, self-contained context, the options weighed (including the rejected ones), and why
  it's the user's call.

## Input parsing

The skill is invoked with one of:

- **Explicit ticket list** — `/orchestrate TICKET-1 TICKET-2 TICKET-3`. Parse the IDs directly.
- **Batch reference** — `/orchestrate batch 1 of sprint 12`. Read the sprint/iteration plan, find the
  batch assignment, extract the ticket IDs.
- **Mixed** — parse explicit IDs and resolve the batch reference; combine and de-duplicate.

**Always resolve the surrounding context**, even for an explicit list: read the sprint/iteration plan
(goals, batch structure, dependencies) and any key specs it points to. The plan carries inter-ticket
dependencies and sequencing rationale that the individual ticket docs don't.

## Phase 0: Ticket-readiness gate (before any dispatch)

**The developer subagent starts with zero context** — it reads the project's `CLAUDE.md`, the plan, and
the ticket, and nothing else. If the ticket is vague, it will guess. Your job is to ensure every ticket is
a self-contained, unambiguous implementation brief. **This gate is a checks-and-balances mechanism: there
is no guarantee a human groomed the ticket well, so the orchestrator verifies it.**

Read every ticket doc thoroughly. For each, verify and enrich:

### 0a — Completeness
The ticket has: a title/ID; status; priority; a size estimate; **Context** (why this work exists, not just
what to do); **Approach** (concrete steps); **Files** (everything that changes); **Acceptance Criteria**
(specific, testable); **Dependencies** (blocks/blocked-by, or explicitly "None"). Missing field → fix it
before proceeding. Do not dispatch a developer to a half-groomed ticket.

### 0a′ — Current-behavior signature gate (non-negotiable)
Scan the ticket for assertions about how the *existing* code behaves ("X honors the flag", "this returns
`None`", "the handler logs nothing", "Y runs across all records"). **Every current-behavior assertion the
work relies on must be backed by a `⟦SYSTEM-ANALYST-VERIFIED⟧` signature** (see the `system-analyst` agent)
whose `covers=` scope includes the claim.

- Unsigned behavioral claim → the ticket is **NOT ready**. Send it back to grooming, which dispatches the
  `system-analyst` to trace the real behavior and embed the signed report. When *you* explore current
  behavior to enrich a ticket, dispatch the `system-analyst` too — never assert behavior from your own
  grep.
- This is mechanical, not advisory: the code-reviewer FAILS any PR whose ticket carries an unsigned
  behavioral claim, bouncing it back here. Catch it at the gate instead. *(Additive-design tickets that
  assert no existing behavior are exempt.)*

### 0b — Approach quality
Concrete enough for a zero-context developer: explicit file paths (not "update the model"); named classes
and methods; spec references where the work touches documented architecture; links to related/prior
tickets; called-out edge cases; explicit migration/schema instructions where relevant. If the approach is
vague, **rewrite it** — you're the architect; you know where things live.

### 0c — Acceptance-criteria quality
Unambiguous and testable. Fix any that are vague ("works correctly" → a specific assertion). Every code
criterion should imply a test. Split **what ships with the change** (code, generated migrations, tests,
build) from **what runs after it lands** (applying migrations, deploys, backfills) — and include "PR
merged" as the closing criterion.

### 0d — Dependency check
Verify no ticket is blocked by unfinished work; identify what can parallelize vs. must serialize; if a
ticket depends on another in the same batch, plan the dispatch order.

**Only after every ticket passes Phase 0 do you proceed.**

## Orchestration loop

For each batch (group independent tickets for parallel dispatch; serialize dependent ones):

### Phase 1 — Dispatch developer
Launch a `developer` subagent with a one-sentence assignment; it reads its own context. Independent
tickets → parallel Task calls in one message, each in its own worktree. Dependent tickets → serialize.

**Docs-only / planning-only tickets — do NOT dispatch to a worktree subagent; write them yourself.** If a
ticket's whole deliverable is a planning/tracking doc, implement it directly in the primary tree: a
worktree subagent structurally *cannot* persist a planning doc (the worktree copy is blocked by
`protect-worktree-planning.sh`, the primary copy by the platform's shared-checkout guard), so dispatching
one deadlocks — it can write the deliverable nowhere. The orchestrator runs in primary and writes planning
freely; this is the one ticket class you implement rather than delegate.

**Branch target:** branch from the main branch by default. Only instruct the developer to stack on an
unmerged parent branch when the child literally cannot compile or test without the parent's code
(it imports something not yet on main). Stacking adds merge complexity — prefer independence.

**High-sensitivity tickets** (irreversible operations, wide blast radius, a contested design fork): before
dispatch, run the **adversarial ticket-review panel** (see `workflows/ticket-review-panel.js`) — N
independent reviewers attack the groomed ticket on different lenses. Resolve any blocking finding before
dispatching the developer.

**Testing in dispatch:** do not instruct the developer to run the full test suite locally — CI is the quality gate and runs it on every PR. The developer runs only *targeted* tests for the code it changed (per `developer.md`). A full local suite duplicates CI and leaves a long no-output window that risks a stream-watchdog reap; the only local run worth requesting is one CI does not perform (e.g. live/integration tests for LLM-adjacent changes).

### Phase 2 — Open PR
After the developer reports done: verify the branch was pushed, open a PR against the main branch, report
the URL to the user. **Stop — do not merge.**

### Phase 3 — Code review
Launch a `code-reviewer` subagent: `Review PR #{N} for {ticket-id}: {description}.` It invokes the
`code-review` skill (three layers + non-negotiable checklist), posts findings as a PR comment, and reports
the categorized findings back to you. The reviewer renders **no overall verdict** — it reports; you decide.

### Phase 4 — Architect evaluation
**You evaluate every finding — no finding dies in a PR comment.**

The reviewer hands you findings, not a verdict, and you must not supply one on its behalf. Evaluate each
finding against the actual code yourself — "the review looks clean" is not a disposition; reading the code
is. Authority and judgment are the same actor: whoever decides a PR is ready is whoever evaluated the
findings. A confident "Approve" is exactly what lets a real bug through, which is why the reviewer reports
findings only and you make the call.

| Severity | Action |
|----------|--------|
| **Critical / High** | Must fix before merge. Launch a developer subagent. |
| **Medium** | Must fix before merge. Medium is not acceptable debt. Launch a developer subagent. |
| **Low** | **Default: fix now.** Defer to a tracked ticket *only* when the fix genuinely needs design work beyond this ticket's scope — and document why. |

"Pre-existing," "not introduced here," "acceptable at current scale," and "more overhead than the fix"
are **not** valid reasons for inaction. If it was found, it gets fixed or ticketed. The question is never
"is this blocking?" — it's "fix now or fix later?", and the default is now.

### Phase 5 — Fix cycle
Launch a `developer` with specific remediation instructions, **including the existing PR branch name** so
fixes land as new commits on the same branch. **Never create a separate `-review-fixes` branch** — satellite
branches strand commits the PR never sees and survive merge as orphans. If the PR branch is locked by
another worktree, push to it from the orchestrator (`git push origin <source>:refs/heads/<pr-branch>`)
rather than branching around it. **Never `git worktree remove`/`prune`** mid-flight — it can crash an open
editor. Non-trivial fixes → re-review with another `code-reviewer`. Trivial fixes → verify yourself by
reading the diff. Repeat until clean.

### Phase 6 — Ready to merge
Report "PR #{N} for {ticket-id} is ready to merge." **Do not merge.** List any post-merge (Ops) criteria.
**Do not wait** — move to the next ticket. If a stacked PR exists on this branch, remind the user to use a
regular (non-squash) merge so downstream rebases stay clean; the last PR in a chain can be squashed.

### Phase 7 — Status update
The developer cannot write planning/tracking docs from its worktree, so **you persist the per-ticket status
update from the developer's report** — write it where your project keeps status updates, named for the
ticket (what it built, key decisions, test results, issues/follow-ups, taken from its final report). You are
in the primary tree, so this write is unblocked. After the whole batch completes, also write a batch status
update: tickets covered, what was built, key decisions, review findings addressed, PRs opened, current
state.

## Error handling

- **Developer subagent fails:** read the error, diagnose. **First, recover any committed-but-unpushed work
  from the dead worktree** — a runtime "stream-death" can reap an agent *after* its `git commit` but
  *before* its `git push`, stranding a real commit in the worktree. Find it (`git -C <worktree> log
  origin/<branch>..HEAD`) and push it (`git push origin <sha>:refs/heads/<pr-branch>`) before
  re-dispatching, so you don't rebuild work that already exists. Then fix the ticket (if the spec was
  wrong) or re-dispatch with corrected instructions.
- **Review finds a design-level (Layer 1) issue:** stop the fix cycle. Escalate to the user with the
  concern and proposed alternatives (the door-knock format above). Don't proceed until it's resolved.
- **CI fails:** do not declare ready. Investigate whether it's a test issue or an implementation issue;
  fix before proceeding.
- **Merge conflict:** rebase onto the main branch and resolve properly. After a parent was squash-merged,
  a plain rebase of a stacked child fails (git tries to replay the parent's now-squashed commits) — use
  `git rebase --onto <main> <last-parent-commit> <branch>`, then `git push --force-with-lease`.
- **A background agent with no completion/failure notification is RUNNING, not dead — never diagnose a reap from worktree state.** The stream watchdog is a *no-progress* timer, not a wall-clock cap: an agent that keeps streaming can run far past the window and still finish. An empty task list, zero commits on the branch, or half-written files in the worktree are all equally consistent with an agent that is *still working* and simply hasn't committed yet. A genuine reap arrives as an explicit `failed: stalled … (stream watchdog)` notification. Until you have that notification (or a non-blocking `TaskOutput` confirming the agent exited), treat the agent as live — do **not** re-dispatch it, decompose its ticket, or harvest-and-replace its worktree, or you risk spawning duplicate work (and duplicate PRs) against a healthy run.
- **Repeated stream-death (silent reap after a successful tool result):** this is a runtime condition the
  harness can't prevent, only bound. On a success-rate cliff (≥2 consecutive reaps after a clean batch),
  **back off and surface "runtime degraded" to the user** — do NOT switch to serial dispatch (it treats
  the wrong cause and burns wall-clock). The developer's atomic `commit && push` bounds the per-agent
  blast radius; the recovery step above retrieves whatever still strands. The same reap can orphan an
  orchestrator write to a planning doc whose result landed before the stream died — commit *and* push
  planning writes promptly rather than leaving them uncommitted across many tool calls.

## Output

After the loop completes for all assigned tickets, summarize: tickets processed (with final status); PRs
opened (numbers/URLs); review cycles per ticket; architectural decisions made (especially Low-finding
dispositions); deferred items (new tickets created); blockers needing user attention; next steps (Ops
items, remaining batches, follow-ups).
