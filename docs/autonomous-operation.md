# Running autonomously — `/stepping-away`

The point of the harness is that you can hand it a plan, leave, and trust the work to come back done — or
paused cleanly at a decision only you should make. `stepping-away` is the skill that grants that mandate;
`summarize-issue` is how the session knocks when it hits a gate. This doc explains the mandate and shows
the handover prompt that sets it up well, because the quality of an autonomous run is mostly decided by the
quality of that first message.

## The mandate, in one paragraph

Under [`stepping-away`](../skills/stepping-away/SKILL.md), the session completes the current plan without
your input: it answers its own questions by reading the project's documented principles, decides on the
merits (never gating on effort or timeline), logs each non-trivial decision to a reviewable artifact, and
stops only at a high-blast-radius decision — something hard to reverse, outward-facing,
production-affecting, or destructive. At those points it leaves the system in a safe paused state and
knocks with a [`summarize-issue`](../skills/summarize-issue/SKILL.md) briefing you can act on in two
minutes.

## How it composes with the rest of the loop

`stepping-away` is the operating posture; the other skills are what it runs:

- **`orchestrate`** drives the work — readiness gate, dispatch, review, disposition, status. Autonomy
  raises the stakes on the [checks-and-balances loop](checks-and-balances.md), not the license to skip it.
- **`architect-reminder`** keeps decisions on merit when "that's a lot of work" starts creeping into a
  recommendation — the exact failure autonomy is prone to.
- **`summarize-issue`** is the escape hatch: the one way the session is allowed to spend your attention,
  and only at a real gate.

The session stays inside the control loop the whole time. It is empowered to hit the brakes and rewind the
moment it notices the work veering from process — that self-correction is what makes unattended operation
safe, and it's why you can leave.

## The handover prompt

A good handover does five things in one message: points at the operating contract, gives the current state
plainly, names the assignment, draws the hard gates, and hands over. Use this shape:

1. **Frame** — what's being handed over, and to do what (`/orchestrate`).
2. **Orient** — the docs to read in full first: the root `CLAUDE.md` (role, quality bar, decision-hygiene
   rubric), the product strategy, a system overview, the process doc, and the planning map.
3. **Disciplines** — the best-practices docs to read before writing code (data access, external
   integrations, testing — whatever your project gates on).
4. **Context for this session** — what just landed and was validated, and the *verified* current state
   (branch/commit, environment health, the numbers that matter). State it as fact the session can rely on.
5. **The assignment + pre-flight** — the entry-point docs (sprint plan, handoff) that carry the ordered
   items, the standing authorizations (what it may do without you), and the sharp edges; then a cheap state
   check to run before starting.
6. **The mandate + the hard gates** — step away, complete autonomously, and the explicit list of actions
   that are *never* autonomous. Tell it to prepare everything up to those gates and door-knock when ready.

### Worked example (generalized)

> **The sprint is open and I'm handing it to you to `/orchestrate`.**
>
> **Orient (read these first, in full):**
> - `CLAUDE.md` (root) — the operating contract: role, quality bar, the decision-hygiene rubric, and the
>   Context Cascade map. Before anything else.
> - `planning/specs/STRATEGY.md` — the product vision and what we optimize for.
> - `planning/specs/foundational/system-overview.md` — understand the whole system before you change it.
> - `planning/PROCESS.md` — the sprint lifecycle, the orchestrator ↔ subagent model, the ticket template,
>   the merge policy.
> - `planning/CLAUDE.md` — where each planning artifact lives.
>
> **Disciplines (before writing code):** the project's data-access, external-integration, and testing
> best-practices docs — and the data-safety model, since this sprint operates the production path.
>
> **Context for this session:** the previous sprint closed successfully — the feature work merged with my
> authorization and the environment is healthy. Verified current state: `main` and `origin/main` agree at
> the latest commit; staging holds the validated candidate; no open PRs. Item 1 of this sprint is done and
> I validated it. If I find anything later, I'll raise it as an explicit loop-back.
>
> **The assignment:** you're the orchestrator. Read `planning/sprints/<N>/sprint-plan.md` and
> `planning/sprints/<N>/HANDOFF.md` as your entry points — the handoff carries the ordered assignment
> (items 2 → 3 → 4), the standing authorizations (you may dispatch, review, and ready PRs without me;
> merges go through the full loop), the verified current state, and the sharp edges (trace current behavior
> before grooming; the known traps from last sprint). Confirm `git rev-parse main origin/main HEAD` agree
> and `gh pr list --state open` is empty, then start.
>
> **I'm stepping away.** Complete the plan autonomously — don't pause for questions you can answer from the
> documented principles. **THE HARD GATES:** applying a migration to production, any direct production-data
> mutation, the cutover — never autonomous; the cutover is joint and executes only together with me.
> Prepare everything up to those gates and door-knock me with `/summarize-issue` when the end-sequence is
> ready to run. Until then, `/stepping-away`.
>
> Keep `/architect-reminder` and the process disciplines in mind as you `/orchestrate`. You're empowered to
> hit the brakes and rewind the moment you notice anything veering from process — the checks-and-balances
> loop is the control, and you are part of it.

### The hard gates

The hard gates are the few actions that must never happen without you: irreversible, outward-facing,
production-affecting, or destructive. Naming them explicitly is what makes the rest of the autonomy safe —
the session knows exactly where its authority ends, so it can move fast everywhere else and stop precisely
at the edge. Everything up to a gate (the build, the review, the validation, the staging dry-run) is the
session's to complete; the gate itself is yours.

## What you get back

On return you read three things instead of having sat in the loop: the **decision log** (every non-trivial
call, the options weighed, and the principle that settled it), any **door-knock briefings** the session
raised at gates, and the **final status**. If the run was clean, the gates are prepared and waiting; if it
hit something only you can decide, it's paused safely with the briefing ready.
