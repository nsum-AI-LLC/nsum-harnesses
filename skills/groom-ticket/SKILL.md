---
name: groom-ticket
description: "Groom a ticket into a self-contained implementation brief. Guides context gathering, interactive refinement, and writing a ticket that a zero-context developer can execute without guessing."
---

# Groom Ticket Skill

A well-groomed ticket is a **knowledge transfer document**. A developer with zero context picks it up and knows exactly what to build, why, and how to verify it. If the developer has to explore the codebase just to understand the ticket, the ticket failed.

At minimum a ticket should specify: the problem (with evidence), the approach (with real file and function names), the files to touch, acceptance criteria (split into what ships in the change vs. what runs after it lands), and dependencies. Adapt these fields to your tracker.

## Step 1: Gather Context

Before writing anything, deeply understand the problem space. The ticket's quality is bounded by your understanding.

**Explore the current behavior.** Trace the code path from entry point to output. Note file paths, function names, line numbers. Run commands and quote actual output.

**When the ticket's correctness depends on how existing code behaves, verify it — don't assert it from a grep.** A ticket that claims "step X honors the flag" or "this returns `None`" and is *wrong* sends a developer down a path built on a false premise that a reviewer (or production) discovers later. Dispatch a `system-analyst` (Agent tool, `subagent_type: system-analyst`) with the precise behavioral question; it traces the real execution path and returns a `file:line`-cited report ending in a `⟦SYSTEM-ANALYST-VERIFIED⟧` signature. Copy that report and its signature verbatim into the ticket's **Current Behavior (verified)** section. Downstream, the developer and code-reviewer check for that signature before trusting any current-behavior claim — so an unverified assertion will bounce the ticket straight back here.

**Trace the history.** Find the change that created this code (`git log --oneline -- <file>`, your issue tracker, prior session logs). Every architectural decision had a reason — find it before proposing changes.

**Study failure cases.** Read the tests for the components involved. Run actual metrics (timings, counts, error rates). Concrete numbers replace hand-waving.

**Map what's adjacent.** What calls this code? What consumes its output? If it's part of a multi-step pipeline, understand what each step uniquely handles.

## Step 1b: Challenge the Premise

After gathering context, pause and ask: **is the proposed solution architecturally sound?** This is not a cost/benefit calculation or an excuse to avoid work — it's a design quality gate.

- **Does it generalize?** A solution pattern-matched to one motivating example will break on inputs you haven't seen. If it only works for the cases you've tested, it's not ready to run unsupervised.
- **Does it fit the architecture?** Does it follow existing patterns, or introduce a new concept that needs justifying? New abstractions carry ongoing maintenance cost — they need to earn their place.
- **Would it survive six months unsupervised?** If the answer is "only if the inputs look like today's," the solution is fragile regardless of how many tests it has.
- **Is there a simpler path that's equally sound?** A config change or reusing an existing component may solve the problem without new code. Prefer these when they're architecturally equivalent — but never prefer them just because they're less work.

**The output of this step can be "don't build this."** A well-reasoned decision not to build is better than a well-tested implementation of the wrong thing. But "don't build" must be justified by architectural unsoundness, not reluctance to do the work.

## Step 1d: Is this one ticket, or an epic wearing a ticket's clothes?

A ticket is one change, reviewable in one pass, shippable on its own. Work larger than that is an
epic: a guiding design, a sequence of tickets, and a deployment plan that says what ships first and
what turns on last.

**Any one of these means the work is an epic. Stop drafting the ticket and draft the epic.**

- The estimate is three or more sessions. That is a sequence, not a ticket.
- The Approach needs an **internal ship order**. If you are numbering parts and saying which lands
  first, you have written a deployment plan; its steps are the tickets.
- The Approach names **parts that could ship separately** — a config, a service, a UI change, an
  instrument, a migration.
- **Invariants span the parts.** Rules that "every part obeys" are epic architecture, and they belong
  in the guiding design where each ticket reads them.
- The diff would plausibly exceed **~800 lines or ~15 files**.

Reviewer defect-detection degrades as a diff grows — a property of the artifact, not a matter of
taste. A large change is reviewed worse than the same change delivered in sequence, and it cannot be
bisected.

### What to produce instead

1. **The epic directory** with a README carrying the guiding design, the Definition of Done, and the
   ticket inventory.
2. **A deployment plan in that README** — the ordered sequence, what each step ships, and what makes
   each one safe to land alone. A part that cannot ship alone rides behind a flag committed disabled,
   flipped by the last ticket in the sequence. Ordering exists so no step leaves the system in a
   state the next step must rescue.
3. **One ticket per step**, each groomed to this standard, each independently reviewable and
   mergeable, each naming its predecessor.
4. **A commitment for the sequence** — its own swim lane or its own sprint, so the orchestrator
   dispatches the steps in order rather than a developer discovering the order inside a brief.

An epic's ticket inventory is not its deployment plan. Filing siblings around a large central ticket
decomposes along the axis of what other work exists, not the axis that governs delivery.

Decomposition is a review-quality instrument and its value is spent at review time. Splitting after
the review has happened does not recover it, which is why this gate is here and not later.

## Step 2: Refine Interactively

**Ask the user questions.** The best tickets come from dialogue, not monologue. After your initial exploration, surface what you found and ask:

- "Here's what I found about why it works this way — does this match your understanding?"
- "I see two approaches: {A} and {B}. {A} handles {X} better but misses {Y}. Which trade-off matters more?"
- "The tests cover {these cases} but not {those}. Are there failure scenarios you've seen that I should account for?"

Don't assume you have the full picture. The user has context from operating the system that isn't in the code.

## Step 3: Write the Ticket

Transfer everything you gathered into a document a zero-context developer can execute.

**Context** — Tell the story: what's wrong (with evidence), why it was built this way (reference prior changes), and why the current approach fails (with concrete failure cases).

**Current Behavior (verified)** — If the ticket relies on any claim about how existing code behaves, paste the `system-analyst`'s `file:line`-cited report and its `⟦SYSTEM-ANALYST-VERIFIED⟧` signature here (see Step 1). Omit this section only for purely additive work that asserts nothing about existing behavior.

**Approach** — Be prescriptive: name exact files, functions, and line numbers. Show code snippets for the shape of each change. Explain WHY for non-obvious choices (why this algorithm, this threshold, this data structure). Show what stays unchanged — this prevents scope creep.

**When presenting options:** if the approach involves a choice between alternatives, state the recommendation clearly AND the justification — especially when informed by codebase history or prior failures. A developer who sees "Option (c) is recommended" without understanding WHY will substitute their own judgment and may reintroduce the problem the recommendation was designed to avoid.

**Project-specific patterns** — If your project has conventions for data access, queries, migrations, concurrency, or performance (e.g. "batch writes, never per-row loops"; "no unbounded queries on hot paths"), point the ticket at those rules and verify the approach against them. A ticket whose approach violates a known project rule is not groomed.

**Verify references against reality** — Every file, function, and command the ticket names must exist (or be explicitly marked "created by this ticket"). For code snippets, confirm the fields and APIs you reference actually exist on the types you're calling. For any command in the instructions, run its `--help` and confirm the flags match — don't write commands from memory or by analogy. A ticket with unverified references is not groomed.

**Acceptance criteria — split what-ships from what-runs-after.** Separate criteria satisfied *by the change itself* (code written, tests pass, build succeeds) from criteria that require *running something after it lands* (migrations, deploys, data backfills, other state-mutating commands). This matters especially for isolated or worktree-based development: a subagent working in an isolated checkout that shares state with others (a database, a queue) must NOT run commands that mutate that shared state — those are post-merge steps an orchestrator runs. Keep "ships with the change" criteria limited to writing code, generating (not applying) migrations, running tests, and building.

**Developer guide** — The knowledge transfer: how the relevant system works end-to-end, what data is available at the change point, why preserved components aren't redundant (with the failure case that proves it), which tests to adapt vs. leave alone, and a numbered implementation order.

**Files** — Every file to create or modify. The developer should not need to discover files on their own.

## Output

Write the ticket where your team tracks work, and report: its location, a two-sentence summary, and any open questions that need user input before the ticket is committed to a sprint.
