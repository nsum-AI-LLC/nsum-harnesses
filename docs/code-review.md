# Code Review — the layered methodology, and how to make it yours

Companion to [`skills/code-review/SKILL.md`](../skills/code-review/SKILL.md). Code review is where the loop
confirms that best practices were actually followed, so the shipped skill is a generic core you extend with
your own stack-specific checks.

This doc covers the two ideas worth keeping as-is, and how to grow the rest toward your project.

## The two ideas that generalize

### 1. Layered evaluation — in order

```
Layer 1: SHOULD.    → Is this the right approach?
Layer 2: DOES.      → Does the implementation actually do it?
Layer 3: SURVIVES.  → What happens when things go wrong?
```

The ordering is the point. The most common review failure is skipping Layer 1 — diving into the
implementation of an approach that shouldn't exist in this form, and producing a meticulous review of the
wrong thing. **Correct code that solves the wrong problem is still wrong.** Layer 1 explicitly ends with a
gate: "approach is sound → proceed," or "stop — the design needs discussion."

- **SHOULD** reads the ticket and acceptance criteria, asks "does the platform already solve this?",
  weighs the alternatives the ticket dismissed, checks the complexity budget, and verifies *someone reads
  what this code writes* (output with no consumer is dead on arrival).
- **DOES** verifies each stated goal, then does the tracing (below), then runs the non-negotiable
  checklist, then exercises edge cases with a real script rather than reasoning about them.
- **SURVIVES** asks about failure cascades, recovery and reversibility, and observability — the
  3-a.m.-pager questions.

### 2. Tracing the change through its neighbors

A diff read in isolation hides its two most dangerous classes of bug. The skill traces **both
directions**:

- **Upstream — what changed silently.** For every modified function, read the *pre-change* version
  (`git show <base>:<path>`) and diff the behavior, not just the text. This catches the reordered guard,
  the changed default, the control-flow restructuring that alters *when* code runs — changes the author's
  stated intent never mentions because the author didn't notice them. The skill makes this concrete with a
  **control-flow audit** (paths before vs. after) and a **data-flow trace** (origin → transformations →
  sink).
- **Downstream — what depends on this.** Grep for the callers of every changed function. A signature
  change, a renamed argument, a different return shape, or a new error behavior breaks callers that the
  diff never shows. A change that compiles in isolation but breaks three callers is a failed review.

Keep these. They are the difference between reviewing a diff and reviewing a *change*.

## The non-negotiable checklist

Layer 2 runs a checklist where each row is an analytical step and a FAIL produces a finding. The shipped
nine rows are the framework-neutral core: no "good enough for now"; no operations whose cost grows
unbounded with data; real error handling; tests for decisions (not plumbing); externalized secrets/config;
consistency with existing patterns; no dead code or untracked TODOs; cross-boundary contracts kept in
sync; and current-behavior assertions backed by a system-analyst signature.

Two rules make the checklist trustworthy:

- **Cross-check:** every FAIL must map to a finding, and every finding that maps to a row must FAIL that
  row. A query concern flagged in the prose but a PASS on the cost row is sloppy analysis — resolve it
  before posting.
- **Every finding requires a disposition.** Severity communicates *impact*, never *whether action is
  required*. The skill bans "blocking / non-blocking / nit" vocabulary precisely because it smuggles in an
  "optional" tier.

## No overall verdict — and why

The reviewer surfaces findings with accurate severities and stops. It does **not** output "Approve,"
"Request Changes," or "LGTM." Deciding what the findings mean — fix now, ticket it, or ready to merge —
belongs to the orchestrator, which evaluates each finding against the code itself.

This is a hard-won rule, not a style preference. When the reviewer handed over a verdict, the orchestrator
treated it as permission to stop evaluating: it conflated "saw a green check" with "read the findings." A
real bug once shipped past review because the reviewer wrote "Medium — monitor after deploy" next to an
"Approve," and the orchestrator heard "Approve" and moved on. The fix was to delete the verdict. The
reviewer reports findings; the orchestrator dispositions each one.

The principle underneath: **authority and judgment are the same actor.** Whoever decides a change is ready
must be the one who evaluated the findings, freshly, against the code. Delegating that judgment to a
reviewer's verdict and then citing the verdict to justify the merge is circular — it recreates the
rubber-stamp. The reviewer's report is an *input* to the orchestrator's decision, never the decision.

Keep this when you adapt the skill: a per-row checklist verdict (PASS / FAIL / NA) is fine — that's
evidence for a specific standard. A single overall Approve / Request Changes is not.

## Customizing it — where the real value is

The highest-leverage review checks are specific to *your* stack, and the skill is built to be grown. The
production project this came from carries roughly **fourteen** checklist rows; the public version ships
**nine** and tells you to add the rest. Do that:

1. **Add checklist rows for your platform's known foot-guns.** The ones worth their weight are the
   mistakes your codebase *actually* makes repeatedly. Examples from real projects:
   - ORM query patterns that silently produce full table scans, Cartesian joins, or per-row I/O in a loop.
   - Framework lifecycle hooks with surprising ordering or re-entrancy.
   - Thread-safety rules for instances shared across concurrent invocations.
   - Serialization contracts between a backend and a typed frontend (a response shape change needs a
     matching client-type change in the same PR).
   - Migration/constraint rules — e.g. "data cleanup ships in the *same* migration as the constraint, not
     in an ops checklist," because CI auto-applies migrations before any human runs a script.

2. **Make the performance row concrete.** Generic row #2 says "trace expensive operations to their real
   cost." For your data layer, spell out how: how to read the generated query, where indexes must exist,
   which access patterns are forbidden, what "bounded" means for your store.

3. **Point reviewers at your authoritative docs.** "Consult `docs/database-best-practices.md` for batch
   and query rules" turns an instinct into an enforceable standard with a single source of truth.

4. **Tighten the mandate and the output contract.** If your bar forbids deferring any finding, say so. If
   you require a posted artifact (a PR comment, a sign-off), make it mandatory. The shipped skill posts a
   structured comment and signs off as Claude; adjust the format to your conventions.

Keep the bones — three layers in order, the pre-change baseline, the control-flow and data-flow traces,
the downstream caller search, and the cross-check rule — and let the leaves grow toward your project. A
review skill that never accumulates your stack's specific checks is leaving most of its value on the table.

## How it fits the rest of the system

The reviewer is the last step in two chains:

- It fails any PR whose ticket carries an unsigned current-behavior claim — the end of the
  [signature chain](checks-and-balances.md#a-worked-example-the-signature-chain).
- Its findings feed the orchestrator's Phase 4 disposition, where every finding is fixed or ticketed. The
  reviewer finds and reports; the orchestrator ensures each one is acted on.
