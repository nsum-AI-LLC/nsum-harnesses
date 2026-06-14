---
name: code-review
description: Thorough, layered code-review methodology for PRs and local branches — challenge the approach, verify the implementation, trace upstream and downstream impact.
---

# Code Review Skill

This is a **general-purpose** review methodology: a starting point you extend with your project's own
stack-specific checks (see [Customizing this skill](#customizing-this-skill) at the end). It encodes two
things that generalize across every codebase — **layered evaluation** and **tracing the change through
its callers and callees** — and deliberately leaves the framework-specific rules to you.

## Core philosophy

**Challenge the approach before verifying the implementation.** Correct code that solves the wrong
problem is still wrong.

**Review the delta, not just the destination.** A change is a *modification to existing behavior*. The
question is never only "is the new code good?" — it is "is this *change* intentional, complete, and safe
for everything that depended on the old behavior?"

## Reviewer's mandate

Enforce your project's quality bar. Treat these as defaults; tighten them to your standards:

- **You report findings; you do not render a verdict.** No "Approve," "Request Changes," or "LGTM" —
  not in the review, not in your report back. Surface every finding with an accurate severity and stop
  there. Whether the change is ready to merge is the orchestrator's call, made by evaluating the findings
  against the code. A verdict from you lets that evaluation get skipped — see
  [the user guide](../../docs/code-review.md).
- **Every finding requires a disposition.** The person who receives your review either fixes the finding
  or opens a tracked ticket for it. There is no "noted" / "accept without action" outcome. If you flag
  it, it gets worked.
- **Severity signals impact, not optionality.** Use severity labels (Critical / High / Medium / Low) to
  communicate *how bad*, never *whether action is required* — action always is.
- **Vocabulary rule:** avoid "blocking / non-blocking / nit." Those words create a false hierarchy where
  some findings are optional. Say what the finding *is* and how severe its impact is; let the owner
  decide the sequencing.

## The three-layer model

Every review addresses three layers, **in order**:

```
Layer 1: SHOULD.    → Is this the right approach?
Layer 2: DOES.      → Does the implementation actually do it?
Layer 3: SURVIVES.  → What happens when things go wrong?
```

Skipping Layer 1 to dive straight into Layer 2 is the single most common review failure — you end up
polishing a well-built answer to the wrong question.

---

# Layer 1 — SHOULD (design review)

Before reading the code line by line, answer: **should this change exist in this form?**

### 1.1 Gather context

1. **Read the linked work item / ticket.** Its acceptance criteria define what "done" means. If you
   cannot determine what work this change implements, say so explicitly in the review — that is itself a
   finding.
2. **Read the change description.** What does the author claim it does? Does that match the acceptance
   criteria?
3. **Read the surrounding planning/spec context** the ticket points to, if any.
4. **Fetch the full diff** to a file and read it with the Read tool — never review from a skimmed
   terminal scroll.

### 1.2 "Does the platform already solve this?"

Before accepting custom logic, check whether the language, framework, standard library, or an already-
imported dependency provides a built-in solution. Hand-rolled versions of things the platform already
does are a maintenance liability and usually buggier than the built-in.

### 1.3 Alternatives

For any non-trivial change: the ticket or spec usually records the chosen approach and the alternatives.
Scrutinize the reasoning with fresh eyes. Is any deviation from the intended design justified? What would
a senior engineer who *disagreed* with this approach propose instead — and is there a reason that's wrong?

### 1.4 Complexity budget

Does the solution's complexity match the problem's? Could it be done with less code, fewer moving parts?
What's the maintenance burden in two years?

### 1.5 Consumer verification — "who reads what this writes?"

For any code that persists or emits state (records, events, cache entries, files, messages): identify the
specific consumer. **If nothing reads the output, the code is dead on arrival** — flag it. This is the
first half of impact tracing: where does this change's output *go*?

**Layer 1 output:** either "approach is sound — proceed to Layer 2" or "stop — the design needs
discussion." Don't review the implementation of an approach you believe is wrong.

---

# Layer 2 — DOES (implementation review)

Now verify the implementation is correct — and trace the change through the code around it.

### 2.1 Intent verification

List the goals (from the change description) and the acceptance criteria (from the ticket). As you read,
check off each one when you confirm it's implemented. Flag any that are partial or missing.

### 2.2 Pre-change baseline — trace UPSTREAM (critical)

**For every function the change modifies, read the version before the change.**

```bash
git show <base-branch>:<path> > /tmp/pre_<filename>
```

Compare before and after: what behavior existed before, what exists now, and **is the delta
intentional?** This is what catches accidental behavior changes hidden inside a "refactor" — a reordered
guard, a changed default, a control-flow restructuring that alters *when* code runs. The author's stated
intent is about the new behavior; this step audits what *silently changed*.

### 2.3 Systematic diff analysis

Read the diff file with the Read tool. For each changed file: what is the change doing? Does it match the
stated intent? Logic errors, off-by-one, wrong operator, inverted condition? Does it follow existing
patterns?

**Your scope is not limited to the diff.** If the changed code calls functions you don't understand, or
uses data whose origin is unclear — go read the source. Grep for definitions, follow imports, read whole
files. You have codebase access; use it. A tech lead doesn't say "I can't see it from the diff" — they go
find it. **Guardrail:** never claim "X wasn't done" without verifying against the actual diff and source.

### 2.4 Control-flow audit

When conditionals are added, removed, or restructured: list the execution paths *before* the change and
*after*, and confirm every difference is intentional. New early-returns, changed short-circuits, and
moved guards are where silent regressions hide.

### 2.5 Data-flow trace

Follow the data: where does it originate, what transformations happen to it, where does it end up? Are
types and units consistent the whole way through? A value that's correct at the source and correct at the
sink can still be corrupted by a transformation in the middle.

### 2.6 Non-negotiable checklist

Run this **during** Layer 2 analysis (not after). Each row is an analytical step; a FAIL produces a
finding at the indicated severity. This is the **generalizable core** — add your stack's specific checks
to it (see [Customizing this skill](#customizing-this-skill)).

| # | Standard | How to evaluate | FAIL severity |
|---|----------|-----------------|---------------|
| 1 | No "good enough for now" | Look for shortcuts: values hardcoded that should be configurable, edge cases acknowledged in a comment but not handled, TODO-shaped patterns. Ask: "would this survive a 10× increase in load/data without changes?" | High |
| 2 | No operations whose cost grows unbounded with data | **Trace each expensive operation to its real cost.** Unbounded queries/scans, O(n²) over data, per-item I/O (DB / network / filesystem) inside a loop, missing pagination. A cap on *results processed* does NOT bound an underlying full scan. Per-item writes in a loop should be batched. | High |
| 3 | Error handling | No swallowed exceptions, no catch-everything blocks that hide failures. External calls (I/O, network, subprocess) are wrapped; errors are logged with enough context to diagnose, or re-raised. | Medium |
| 4 | Tests for new/changed behavior | Map each **decision** in the diff (a branch, predicate, scoring rule, format conversion) to a test. Do **not** demand tests for plumbing with no decision logic (thin wrappers, framework behavior) — that's a false positive. | High |
| 5 | Secrets & config externalized | No credentials, tokens, or environment-specific values hardcoded in source. Configuration lives in config/env, not literals. | Medium |
| 6 | Consistent with codebase patterns | For each new function/class, find the nearest existing analog. Same signature shape, naming, error-handling, logging? Deviations need a reason. | Medium |
| 7 | No dead/commented-out code, no untracked TODOs | Scan for `TODO`/`FIXME`/`HACK` without a linked ticket, commented-out blocks, unused imports, unreachable branches. | Low |
| 8 | Cross-boundary contracts stay in sync | If an API/interface/schema shape changed, its consumers — clients, shared type definitions, downstream callers — are updated **in the same change**. (See § Downstream impact.) | High |
| 9 | Current-behavior assertions are verified | If the ticket asserts how *existing* code behaves and the implementation relies on it ("step X honors the flag", "this returns `None`", "the handler logs nothing"), that assertion must carry a `⟦SYSTEM-ANALYST-VERIFIED⟧` signature whose `covers=` scope includes the claim. An unsigned current-behavior claim the change relies on is a FAIL — send it back to grooming to dispatch a `system-analyst`. *(A purely additive change that asserts no existing behavior passes this NA.)* | High |

**Cross-check rule:** after the checklist, reconcile it against your findings. Every finding that maps to
a row must produce a FAIL on that row; every FAIL must produce a finding. Contradictions (flagging a
concern but marking the row PASS) mean sloppy analysis — resolve before posting.

### 2.7 Edge-case verification — don't theorize, run it

Where a change has non-trivial decision logic, write and run a small script that exercises it on: empty
input, missing/malformed data, and boundary conditions (0, 1, max, off-by-one). Observed behavior beats
reasoning about behavior.

---

# Layer 3 — SURVIVES (failure-mode review)

Ask: **what happens when things go wrong?**

- **Failure cascade.** If this component fails, what happens to the things that depend on it? Which
  failures are isolated, which cascade?
- **Recovery & reversibility.** If this fails at 3 a.m., how hard is recovery? Are there partial states
  that are hard to clean up? Is the operation idempotent — safe to retry? Is anything destructive or
  irreversible done without a guard, a dry-run, or a recoverable backup?
- **Observability.** If this misbehaves, will anyone notice? Can you tell *what* failed, not just *that*
  something failed? Are mutations logged?

---

# Downstream impact — trace the CALLERS

The other half of impact tracing. Find everything that depends on what changed:

```bash
grep -rn "changed_function_name" --include="*.<ext>"
```

For each caller, check:

- Who calls this code — other modules, scheduled jobs, CLI entry points, external services?
- Do config files or manifests reference the changed module/interface?
- **Breaking contract changes** — a changed signature, a renamed/removed argument, a different return
  shape or error behavior. Every caller must be updated in the same change, or the break is shipped.

A change that compiles in isolation but breaks three callers is a failed review, not a passed one.

---

# Architectural fit & code quality

Ask whether the code **belongs**, not just whether it works.

- **Structure.** Does new logic live in the right layer? Are module/interface boundaries respected? Is
  business logic separated from I/O and entry-point glue so it's testable on its own?
- **Code smells.** N near-identical functions differing only in a parameter (consolidate); multi-step
  operations a library method does in one call; repetitive copy-paste that should be a loop or helper.
- **Maintenance burden.** Hardcoded values that the world will outgrow; "dual-file" patterns where one
  change requires editing two files in lockstep.
- **Neighborhood cleanup.** While you're in a file, flag adjacent obvious problems — redundant
  conditionals, dead code, stale or misleading comments.

---

# Compile and post

### Organize by severity

Every finding requires action — severity communicates **impact**, not whether it's optional.

- **Critical:** data loss, cascade failures, security vulnerabilities, correctness failures.
- **High:** incorrect results, behavioral regressions, missing error handling, unbounded cost.
- **Medium:** scaling concerns, missing atomicity, pattern violations, maintainability risks.
- **Low:** real but contained — naming, logging gaps, doc staleness. A Low is still a finding to
  disposition; don't signal it can be ignored.
- **Positive:** what the author did well.

### Output format

Post the review as a comment on the PR (e.g. `gh pr comment <N>`). For a local-branch review with no PR,
return the full text instead. Sign off as Claude with the model name.

```markdown
# Code Review: [Title]

**Target:** [PR URL or branch]
**Author:** [name]

## Summary
[1–2 sentences: what this does]

## Design Assessment (Layer 1)
[Approach, alternatives considered, complexity]

## Implementation Findings (Layer 2)
### Critical / High
### Medium
### Low

## Failure Mode Analysis (Layer 3)
[What happens when things go wrong]

## Downstream Impact
[Callers checked; any breaking contract changes]

## Positive Observations
[What the author did well]

## Non-Negotiable Checklist
<!-- Fill in AS you analyze. Every FAIL must have a corresponding finding above. -->
| # | Standard | Verdict | Evidence |
|---|----------|---------|----------|
| 1 | No "good enough for now" | PASS / FAIL / NA | [cite] |
| 2 | No unbounded-cost operations | PASS / FAIL / NA | [cite — trace the operation, not just the result cap] |
| 3 | Error handling | PASS / FAIL / NA | [cite] |
| 4 | Tests for new/changed behavior | PASS / FAIL / NA | [cite] |
| 5 | Secrets & config externalized | PASS / FAIL / NA | [cite] |
| 6 | Consistent with codebase patterns | PASS / FAIL / NA | [cite] |
| 7 | No dead code / untracked TODOs | PASS / FAIL / NA | [cite] |
| 8 | Cross-boundary contracts in sync | PASS / FAIL / NA | [cite] |
| 9 | Current-behavior assertions verified | PASS / FAIL / NA | [cite — check for the signature] |

## Remediation Items
<!-- Every finding above appears here with an explicit action. No finding dies in the review. -->
| Severity | Issue | Required Action |
|----------|-------|-----------------|

## Finding Counts
<!-- No verdict. Do NOT write "Approve" / "Request Changes" / "LGTM" — not here, not anywhere. You surface
     findings with accurate severities; the orchestrator decides disposition and readiness. A verdict lets
     it stop evaluating, which is the failure this prevents. See docs/code-review.md. -->
[Counts by severity, e.g. "2 High, 1 Medium, 3 Low." No verdict.]

🤖 Review by Claude [Model] · Code Review Skill
```

---

# Pre-post verification

- [ ] Layer 1: asked "does the platform already solve this?", weighed alternatives, checked complexity
- [ ] Layer 2: verified each goal/AC, read the pre-change baseline, traced control flow and data flow,
      evaluated every checklist row, exercised edge cases
- [ ] Layer 3: asked "if this fails, what else breaks?", checked recovery and observability
- [ ] Downstream: searched for callers, checked for breaking contract changes
- [ ] Every FAIL row has a finding; every finding has a remediation action

---

# Customizing this skill

This skill is intentionally generic. The highest-leverage review checks are **specific to your stack**,
and they belong in your fork:

- **Add checklist rows (§ 2.6) for your platform's known foot-guns.** Examples: ORM query patterns that
  silently produce full scans or Cartesian joins; framework lifecycle hooks with surprising ordering;
  concurrency/thread-safety rules for shared instances; serialization contracts between a backend and a
  typed frontend; migration/constraint rules ("data cleanup ships in the same migration as the
  constraint"). The willcall.ai project this skill came from carries ~14 such rows; you should grow your
  own set as you discover the mistakes your codebase actually makes.
- **Add a Layer 2 sub-section for performance tracing in your data layer.** Generic row #2 says "trace
  expensive operations to their real cost" — make that concrete for your database/ORM: how to read the
  generated query, where indexes must exist, which access patterns to forbid.
- **Point reviewers at your authoritative docs.** A line like "consult `docs/database-best-practices.md`
  for batch-operation and query rules" turns a vague instinct into an enforceable standard.
- **Tighten the mandate.** If your bar forbids deferring any finding, say so. If you require a posted
  artifact (a PR comment, a sign-off), make it mandatory here.

Keep the bones — three layers, baseline diff, control/data-flow trace, downstream caller search, the
cross-check rule — and let the leaves grow toward your project.
